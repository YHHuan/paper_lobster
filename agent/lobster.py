"""Main lobster agent — one smart lobster with full identity context.

Handles all 6 daily heartbeats:
- explore (morning/evening)
- engage (morning/afternoon)
- create_post (midday/evening)
- reflect (night)
"""

import os
import json
import random
import logging
from datetime import datetime, date

from utils.identity_loader import load_identity
from utils.ai_smell_detector import AISmellDetector
from utils.hook_evaluator import evaluate_hook
from utils.number_validator import validate_numbers
from agent.prompts import (
    EXPLORE_PROMPT, CREATE_POST_PROMPT, CREATE_POST_LENGTH,
    REPLY_PROMPT, REFLECT_PROMPT, SKILL_SELECT_PROMPT,
)
from agent.spawn import spawn_research

logger = logging.getLogger("lobster.agent")

# Limits
MAX_X_DAILY_POSTS = 3
MAX_THREADS_DAILY_POSTS = 3
MIN_POST_INTERVAL_HOURS = 4
SILENT_DAY_PROBABILITY = 0.15
POST_TIME_JITTER_MINUTES = 45
MAX_REPLIES_PER_DAY = {"x": 5, "threads": 8}
MAX_PROACTIVE_PER_DAY = 2
MAX_THREAD_ROUNDS = 3


class Lobster:
    def __init__(self, llm, db, x_poster=None, threads_poster=None,
                 telegram=None, searcher=None, rss_reader=None, jina_reader=None,
                 x_listener=None):
        self.llm = llm
        self.db = db
        self.x_poster = x_poster
        self.threads_poster = threads_poster
        self.telegram = telegram
        self.searcher = searcher
        self.rss_reader = rss_reader
        self.jina_reader = jina_reader
        self.x_listener = x_listener
        self.ai_detector = AISmellDetector()
        self._is_silent_day = random.random() < SILENT_DAY_PROBABILITY

    async def explore(self, mode: str = "morning"):
        """Exploration heartbeat — discover interesting content.

        Args:
            mode: "morning" (AI/tech/science) or "evening" (humanities/cross-domain/oddities).
        """
        logger.info(f"Starting {mode} exploration")

        discoveries = []

        # 1. Search via Tavily
        if self.searcher:
            queries = self._get_exploration_queries(mode)
            for query in queries:
                results = await self.searcher.search(query, max_results=5)
                if results:
                    discoveries.extend(results)

        # 2. RSS feeds
        if self.rss_reader and mode == "morning":
            rss_items = await self.rss_reader.fetch_all_sources()
            for item in rss_items:
                discoveries.append({
                    "title": item["title"],
                    "url": item["url"],
                    "content": item["summary"],
                })

        if not discoveries:
            logger.info("No discoveries found this exploration round")
            return

        # 3. Evaluate with LLM
        identity = load_identity()
        system = f"{identity}\n\n---\n\n{EXPLORE_PROMPT}"

        items_text = "\n\n".join(
            f"--- Item {i+1} ---\nTitle: {d.get('title', 'N/A')}\n"
            f"URL: {d.get('url', 'N/A')}\nContent: {d.get('content', '')[:500]}"
            for i, d in enumerate(discoveries[:10])
        )

        try:
            result = await self.llm.chat_json("lobster", system, items_text)
            evaluated = result.get("items", [])

            for item in evaluated:
                score = item.get("interest_score", 0)
                if score >= 5:
                    await self.db.insert_discovery(
                        source_type="search" if mode == "morning" else "exploration",
                        title=item.get("title", ""),
                        summary=item.get("interest_reason", ""),
                        url=item.get("url"),
                        content_type=item.get("content_type"),
                        interest_score=score,
                        interest_reason=item.get("interest_reason"),
                        language=item.get("language"),
                    )

            high_scores = [i for i in evaluated if i.get("interest_score", 0) >= 7]
            logger.info(f"Exploration {mode}: {len(evaluated)} evaluated, {len(high_scores)} high-interest")

        except Exception as e:
            logger.error(f"Exploration evaluation failed: {e}")

    async def create_post(self):
        """Content creation heartbeat — pick best discovery, write, check, publish."""
        if self._is_silent_day:
            logger.info("Silent day — skipping post creation")
            if self.telegram:
                await self.telegram.notify("🤫 Today is a silent day. Just observing.")
            return

        # Check daily limits
        x_count = await self.db.get_today_post_count("x")
        threads_count = await self.db.get_today_post_count("threads")
        if x_count >= MAX_X_DAILY_POSTS and threads_count >= MAX_THREADS_DAILY_POSTS:
            logger.info("Daily post limit reached for all platforms")
            return

        # Pick best discovery
        candidates = await self.db.get_top_discoveries(limit=3, min_score=7)
        if not candidates:
            logger.info("No high-scoring discoveries to post about")
            return

        discovery = candidates[0]
        discovery_id = str(discovery["id"])

        # Deep read if needed
        source_text = discovery.get("raw_content") or discovery.get("summary", "")
        if self.jina_reader and discovery.get("url") and len(source_text) < 500:
            source_text = await self.jina_reader.read(discovery["url"])
            if not source_text:
                source_text = discovery.get("summary", "")

        # Spawn sub-lobster for deep research if score >= 8
        research = None
        if discovery.get("interest_score", 0) >= 8:
            research = await spawn_research(self.llm, source_text, discovery.get("title", ""))

        # Select skill
        skill = await self._select_skill(discovery)

        # Publish to both platforms via DualPublisher pattern
        results = {"x": None, "threads": None}

        # X version (English)
        if x_count < MAX_X_DAILY_POSTS:
            x_result = await self._write_and_publish(
                discovery, source_text, research, skill,
                platform="x", language="en",
            )
            results["x"] = x_result

        # Threads version (Chinese, independent creation)
        threads_enabled = os.environ.get("THREADS_ENABLED", "false").lower() == "true"
        if threads_enabled and threads_count < MAX_THREADS_DAILY_POSTS:
            threads_result = await self._write_and_publish(
                discovery, source_text, research, skill,
                platform="threads", language="zh",
            )
            results["threads"] = threads_result

        # Link twin posts
        if results["x"] and results["threads"]:
            await self.db.link_twin_posts(results["x"], results["threads"])

        await self.db.mark_discovery_selected(discovery_id)

        # Telegram notification
        if self.telegram:
            await self._notify_post_results(discovery, results)

    async def _write_and_publish(
        self, discovery, source_text, research, skill, platform, language
    ) -> str | None:
        """Write a draft, run quality checks, and publish to one platform.

        Returns post_id in DB or None if failed.
        """
        # Build prompt
        voice_skill = "threads_voice" if platform == "threads" else None
        identity = load_identity(include_skill=skill, platform=platform)
        length_guide = CREATE_POST_LENGTH.get(platform, CREATE_POST_LENGTH["x"])
        system = f"{identity}\n\n---\n\n{CREATE_POST_PROMPT.format(length_guide=length_guide)}"

        user_msg = f"Source material:\nTitle: {discovery.get('title', '')}\n"
        user_msg += f"Content:\n{source_text[:3000]}\n"
        if research and research.get("worth_posting"):
            user_msg += f"\nDeep research notes:\n{json.dumps(research, ensure_ascii=False)}\n"

        try:
            # Write draft
            draft = await self.llm.chat("lobster", system, user_msg, max_tokens=1024)
            if not draft or len(draft.strip()) < 50:
                logger.warning(f"Draft too short for {platform}")
                return None

            # Hook strength check
            hook_score, hook_reason = await evaluate_hook(draft, language, self.llm)
            if hook_score < 7:
                # Rewrite once
                rewrite_msg = (
                    f"The hook scored {hook_score}/10: {hook_reason}\n"
                    f"Rewrite with a stronger opening. Original:\n{draft}"
                )
                draft = await self.llm.chat("lobster", system, rewrite_msg, max_tokens=1024)
                hook_score, hook_reason = await evaluate_hook(draft, language, self.llm)
                if hook_score < 7:
                    logger.info(f"Hook still weak after rewrite ({hook_score}), dropping")
                    if self.telegram:
                        await self.telegram.notify(
                            f"🚫 Draft dropped (hook {hook_score}/10): {draft[:60]}..."
                        )
                    return None

            # AI smell check
            passed, issues = self.ai_detector.check(draft, language)
            if not passed:
                # Rewrite once
                rewrite_msg = (
                    f"AI writing detected: {', '.join(issues)}\n"
                    f"Rewrite to remove these patterns. Original:\n{draft}"
                )
                draft = await self.llm.chat("lobster", system, rewrite_msg, max_tokens=1024)
                passed, issues = self.ai_detector.check(draft, language)
                if not passed:
                    logger.info(f"AI smell still detected after rewrite: {issues}")
                    if self.telegram:
                        await self.telegram.notify(
                            f"🚫 AI smell block ({platform}): {', '.join(issues)}\n{draft[:60]}..."
                        )
                    return None

            # Number validation
            if source_text:
                nums_ok, unverified = validate_numbers(draft, source_text)
                if not nums_ok:
                    logger.warning(f"Unverified numbers: {unverified}")

            # Publish
            post_platform_id = None
            posted_text = draft.strip()

            if platform == "x" and self.x_poster:
                result = await self.x_poster.post_tweet(posted_text, url=discovery.get("url"))
                post_platform_id = result.get("tweet_id")
            elif platform == "threads" and self.threads_poster:
                result = await self.threads_poster.post(posted_text)
                post_platform_id = result

            # Save to DB
            post_id = await self.db.insert_post(
                platform=platform,
                skill_used=skill,
                draft_text=draft,
                language=language,
                discovery_id=str(discovery["id"]),
                posted_text=posted_text,
                hook_score=hook_score,
                ai_smell_check_passed=passed,
                x_post_id=post_platform_id if platform == "x" else None,
                threads_post_id=post_platform_id if platform == "threads" else None,
                posted_at=datetime.utcnow().isoformat(),
            )

            logger.info(f"Published to {platform}: hook={hook_score}, post_id={post_id}")
            return post_id

        except Exception as e:
            logger.error(f"Write/publish failed for {platform}: {e}")
            if self.telegram:
                await self.telegram.notify(f"❌ {platform} publish error: {e}")
            return None

    async def engage(self, mode: str = "morning"):
        """Interaction heartbeat — handle mentions, replies, engagement tracking.

        Args:
            mode: "morning" or "afternoon".
        """
        logger.info(f"Starting {mode} engagement")

        # Update engagement metrics for existing posts
        for interval in ["3h", "24h", "72h"]:
            posts = await self.db.get_posts_needing_engagement(interval)
            for post in posts:
                metrics = None
                if post.get("x_post_id") and self.x_listener:
                    metrics = await self.x_listener.fetch_tweet_metrics(post["x_post_id"])
                if post.get("threads_post_id") and self.threads_poster:
                    try:
                        metrics = await self.threads_poster.fetch_insights(post["threads_post_id"])
                    except Exception:
                        pass
                if metrics:
                    await self.db.update_post_engagement(str(post["id"]), interval, metrics)

        # Handle X mentions and replies
        if self.x_listener:
            await self._handle_x_interactions()

        # Handle Threads replies (dev mode: only own posts)
        threads_enabled = os.environ.get("THREADS_ENABLED", "false").lower() == "true"
        if threads_enabled and self.threads_poster:
            await self._handle_threads_interactions()

    async def _handle_x_interactions(self):
        """Process X mentions and replies."""
        # TODO: Implement with X listener
        pass

    async def _handle_threads_interactions(self):
        """Process Threads replies (dev mode: own posts only)."""
        # TODO: Implement with Threads poster
        pass

    async def reflect(self):
        """Nightly reflection — update curiosity and memory files."""
        logger.info("Starting nightly reflection")

        recent_posts = await self.db.get_recent_posts(days=1)
        today_summary = json.dumps(
            [{"skill": p.get("skill_used"), "platform": p.get("platform"),
              "language": p.get("language"), "hook_score": p.get("hook_score")}
             for p in recent_posts],
            ensure_ascii=False,
        )

        identity = load_identity()
        from agent.prompts import REFLECT_PROMPT
        system = identity
        user_msg = REFLECT_PROMPT.format(today_summary=today_summary)

        try:
            result = await self.llm.chat_json("lobster", system, user_msg)

            # Update curiosity.md
            if result.get("curiosity_update"):
                from utils.identity_loader import update_identity_file
                update_identity_file("curiosity.md", result["curiosity_update"])

            # Update memory.md
            if result.get("memory_update"):
                from utils.identity_loader import update_identity_file
                update_identity_file("memory.md", result["memory_update"])

            # Log insights
            insights = result.get("insights", [])
            if insights:
                logger.info(f"Reflection insights: {insights}")

            # Log token usage
            cost_data = self.llm.get_cost_breakdown()
            total = cost_data.get("_total", {})
            await self.db.log_token_usage(
                heartbeat_type="reflect",
                input_tokens=total.get("tokens", 0),
                output_tokens=0,
                cost_usd=total.get("cost_usd", 0),
                model="claude-sonnet-4-5-20250514",
            )

            # Daily summary to Telegram
            if self.telegram:
                from utils.token_tracker import TokenTracker
                tracker = TokenTracker(self.db)
                budget = await tracker.get_budget_status()
                msg = (
                    f"📊 Today's lobster report\n"
                    f"Posts: {len(recent_posts)}\n"
                    f"Token: ${budget['spent_usd']}/{budget['budget_usd']} "
                    f"({budget['pct']}%)\n"
                )
                if insights:
                    msg += f"Learned: {'; '.join(insights[:3])}"
                await self.telegram.notify(msg)

        except Exception as e:
            logger.error(f"Reflection failed: {e}")

    async def _select_skill(self, discovery: dict) -> str:
        """Use LLM to pick the best skill for a discovery."""
        prompt = SKILL_SELECT_PROMPT.format(
            title=discovery.get("title", ""),
            summary=discovery.get("summary", ""),
            content_type=discovery.get("content_type", "unknown"),
        )
        try:
            result = await self.llm.chat_json("lobster", "", prompt)
            skill = result.get("skill", "research_commentary")
            if skill not in [
                "research_commentary", "trend_analysis", "cross_domain",
                "hot_take", "today_i_learned", "hype_check",
            ]:
                skill = "research_commentary"
            return skill
        except Exception:
            return "research_commentary"

    def _get_exploration_queries(self, mode: str) -> list[str]:
        """Generate search queries based on exploration mode."""
        if mode == "morning":
            return [
                "latest AI research breakthrough counterintuitive",
                "new causal inference natural experiment",
                "neuroscience EEG new findings",
                "medical statistics methodology innovation",
            ]
        else:
            return [
                "unexpected cross-domain discovery science",
                "rediscovered old research forgotten paper",
                "institutional failure design flaw",
                "strange but true scientific finding",
            ]

    async def _notify_post_results(self, discovery, results):
        """Send Telegram notification about published posts."""
        parts = [f"🦞 New discovery published:"]
        parts.append(f"📌 {discovery.get('title', 'N/A')[:60]}")

        if results.get("x"):
            parts.append(f"\n🐦 X (en) ✅")
        elif results.get("x") is None and os.environ.get("THREADS_ENABLED") != "true":
            pass  # X-only mode, no need to show
        else:
            parts.append(f"\n🐦 X ❌")

        threads_enabled = os.environ.get("THREADS_ENABLED", "false").lower() == "true"
        if threads_enabled:
            if results.get("threads"):
                parts.append(f"🧵 Threads (zh) ✅")
            else:
                parts.append(f"🧵 Threads ❌")

        await self.telegram.notify("\n".join(parts))
