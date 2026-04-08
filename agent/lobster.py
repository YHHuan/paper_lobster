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
from agent.deep_research import deep_research
from agent.roles import run_critic, run_editor

logger = logging.getLogger("lobster.agent")

# Prompt for dynamic query generation
DYNAMIC_QUERY_PROMPT = """Based on your current curiosity and recent interests, generate search queries.

Your current curiosity state:
{curiosity}

Your recent memory:
{memory}

Mode: {mode}
- morning: Focus on AI, medical science, statistics, neuroscience, methodology
- evening: Focus on cross-domain, humanities, forgotten papers, institutional design, oddities

Generate 4-5 specific, interesting search queries that follow YOUR current interests.
Keep 1-2 broad queries for serendipity. Make the rest targeted and specific.
Avoid generic queries like "latest AI news" — be specific about what intrigues you.

Respond in JSON: {{"queries": ["query1", "query2", "query3", "query4"]}}"""

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
                 x_listener=None, academic_search=None, browser=None,
                 pdf_reader=None, evolution=None):
        self.llm = llm
        self.db = db
        self.x_poster = x_poster
        self.threads_poster = threads_poster
        self.telegram = telegram
        self.searcher = searcher
        self.rss_reader = rss_reader
        self.jina_reader = jina_reader
        self.x_listener = x_listener
        self.academic_search = academic_search
        self.browser = browser
        self.pdf_reader = pdf_reader
        self.evolution = evolution
        self.ai_detector = AISmellDetector()
        self._is_silent_day = random.random() < SILENT_DAY_PROBABILITY

    async def explore(self, mode: str = "morning"):
        """Exploration heartbeat — discover interesting content.

        Args:
            mode: "morning" (AI/tech/science) or "evening" (humanities/cross-domain/oddities).
        """
        logger.info(f"Starting {mode} exploration")

        discoveries = []

        # 1. Generate dynamic queries based on current curiosity
        queries = await self._generate_dynamic_queries(mode)
        logger.info(f"Dynamic queries for {mode}: {queries}")

        # 2. Search via Tavily
        if self.searcher:
            for query in queries:
                results = await self.searcher.search(query, max_results=5)
                if results:
                    discoveries.extend(results)

        # 3. Academic search (arXiv, Semantic Scholar, PubMed)
        if self.academic_search:
            academic_queries = [q for q in queries[:2]]  # Use top 2 queries
            for query in academic_queries:
                try:
                    academic_results = await self.academic_search.search_all(query, max_results=3)
                    for r in academic_results:
                        discoveries.append({
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "content": r.get("content", ""),
                            "source": r.get("source", "academic"),
                        })
                    logger.info(f"Academic search '{query[:40]}' → {len(academic_results)} results")
                except Exception as e:
                    logger.error(f"Academic search failed for '{query[:40]}': {e}")

        # 4. RSS feeds
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

        # 5. Evaluate with LLM
        identity = await load_identity(self.db)
        system = f"{identity}\n\n---\n\n{EXPLORE_PROMPT}"

        items_text = "\n\n".join(
            f"--- Item {i+1} ---\nTitle: {d.get('title', 'N/A')}\n"
            f"URL: {d.get('url', 'N/A')}\nSource: {d.get('source', 'web')}\n"
            f"Content: {d.get('content', '')[:500]}"
            for i, d in enumerate(discoveries[:15])
        )

        try:
            result = await self.llm.chat_json("lobster", system, items_text)
            evaluated = result.get("items", [])

            stored_count = 0
            for item in evaluated:
                score = item.get("interest_score", 0)
                if score >= 5:
                    # Generate embedding for vector dedup
                    embedding = None
                    embed_text = f"{item.get('title', '')} {item.get('interest_reason', '')}"
                    if embed_text.strip():
                        embedding = await self.llm.embed(embed_text)

                    # Vector dedup: check if similar discovery exists
                    if embedding:
                        similar = await self.db.match_discoveries(embedding, threshold=0.85, count=1)
                        if similar:
                            logger.info(f"Skipping similar discovery: '{item.get('title', '')[:50]}' "
                                       f"(similar to existing, score={similar[0].get('similarity', 0):.2f})")
                            continue

                    await self.db.insert_discovery(
                        source_type="search" if mode == "morning" else "exploration",
                        title=item.get("title", ""),
                        summary=item.get("interest_reason", ""),
                        url=item.get("url"),
                        content_type=item.get("content_type"),
                        interest_score=score,
                        interest_reason=item.get("interest_reason"),
                        language=item.get("language"),
                        embedding=embedding,
                    )
                    stored_count += 1

            high_scores = [i for i in evaluated if i.get("interest_score", 0) >= 7]
            logger.info(f"Exploration {mode}: {len(evaluated)} evaluated, "
                       f"{len(high_scores)} high-interest, {stored_count} stored")

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

        # Deep read — try browser first (JS render), fall back to Jina, handle PDFs
        source_text = discovery.get("raw_content") or discovery.get("summary", "")
        url = discovery.get("url")
        if url and len(source_text) < 500:
            source_text = await self._deep_read_url(url) or discovery.get("summary", "")

        # Multi-step deep research for high-interest discoveries (score >= 8)
        research = None
        if discovery.get("interest_score", 0) >= 8:
            research = await deep_research(
                self.llm, self.db, source_text, discovery.get("title", ""),
                searcher=self.searcher,
                academic_search=self.academic_search,
                jina_reader=self.jina_reader,
                browser=self.browser,
                pdf_reader=self.pdf_reader,
            )

        # Select skill (with engagement history)
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
        """Multi-agent pipeline: Writer → Critic → Editor → Quality Gates → Publish.

        Returns post_id in DB or None if failed.
        """
        # Build prompt
        identity = await load_identity(self.db, include_skill=skill, platform=platform)
        length_guide = CREATE_POST_LENGTH.get(platform, CREATE_POST_LENGTH["x"])
        system = f"{identity}\n\n---\n\n{CREATE_POST_PROMPT.format(length_guide=length_guide)}"

        user_msg = f"Source material:\nTitle: {discovery.get('title', '')}\n"
        user_msg += f"Content:\n{source_text[:3000]}\n"
        if research and research.get("worth_posting"):
            user_msg += f"\nDeep research notes:\n{json.dumps(research, ensure_ascii=False)}\n"

        try:
            # === WRITER: Initial draft ===
            draft = await self.llm.chat("lobster", system, user_msg, max_tokens=1024)
            if not draft or len(draft.strip()) < 50:
                logger.warning(f"Draft too short for {platform}")
                return None

            # === CRITIC: Review the draft ===
            critique = await run_critic(
                self.llm, self.db, draft, source_text,
                platform=platform, language=language, skill=skill,
            )

            critic_verdict = critique.get("verdict", "publish")
            critic_quality = critique.get("overall_quality", 6)

            if critic_verdict == "kill":
                logger.info(f"Critic killed draft (quality={critic_quality})")
                if self.telegram:
                    issues = critique.get("issues", [])
                    await self.telegram.notify(
                        f"🚫 Critic killed draft ({platform}):\n"
                        f"Quality: {critic_quality}/10\n"
                        f"Issues: {'; '.join(issues[:2])}\n"
                        f"Draft: {draft[:60]}..."
                    )
                return None

            # === EDITOR: Revise if critic says so ===
            if critic_verdict == "revise" or critic_quality < 7:
                draft = await run_editor(
                    self.llm, self.db, draft, critique,
                    source_text, length_guide,
                )

            # === QUALITY GATES (kept from v2.5) ===

            # Hook strength check
            hook_score, hook_reason = await evaluate_hook(draft, language, self.llm)
            if hook_score < 7:
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

            # === PUBLISH ===
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

            logger.info(
                f"Published to {platform}: hook={hook_score}, "
                f"critic={critic_quality}, post_id={post_id}"
            )
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

        identity = await load_identity(self.db)
        from agent.prompts import REFLECT_PROMPT
        system = identity
        user_msg = REFLECT_PROMPT.format(today_summary=today_summary)

        try:
            result = await self.llm.chat_json("lobster", system, user_msg)

            # Update curiosity (write to DB, not filesystem)
            if result.get("curiosity_update"):
                await self.db.update_identity_state(
                    "curiosity", result["curiosity_update"], "lobster"
                )

            # Update memory (write to DB, not filesystem)
            if result.get("memory_update"):
                await self.db.update_identity_state(
                    "memory", result["memory_update"], "lobster"
                )

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

            # Auto-evolve: update skill preferences based on engagement
            if self.evolution:
                try:
                    stats = await self._get_skill_engagement_stats()
                    if stats:
                        await self.evolution.propose_and_execute(
                            "update_skill_preference",
                            f"Updated skill preferences from engagement data",
                            {"weights": stats, "source": "nightly_reflect"},
                        )
                    # Execute any pending medium-risk changes past 24h
                    await self.evolution.execute_pending()
                except Exception as e:
                    logger.warning(f"Evolution step in reflect failed: {e}")

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
        """Use LLM to pick the best skill for a discovery, informed by engagement history."""
        # Gather engagement stats per skill from recent posts
        engagement_context = await self._get_skill_engagement_stats()

        prompt = SKILL_SELECT_PROMPT.format(
            title=discovery.get("title", ""),
            summary=discovery.get("summary", ""),
            content_type=discovery.get("content_type", "unknown"),
        )

        if engagement_context:
            prompt += f"\n\nHistorical engagement by skill (last 30 days):\n{engagement_context}"
            prompt += "\nUse this data to inform your choice — but don't blindly chase metrics."

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

    async def _get_skill_engagement_stats(self) -> str:
        """Compute average engagement per skill from the last 30 days."""
        try:
            recent = await self.db.get_recent_posts(days=30)
            if not recent:
                return ""

            skill_stats = {}
            for post in recent:
                skill = post.get("skill_used", "unknown")
                if skill not in skill_stats:
                    skill_stats[skill] = {"count": 0, "total_likes": 0, "total_retweets": 0}
                skill_stats[skill]["count"] += 1

                # Try 24h engagement first, fall back to 3h
                eng = post.get("engagement_24h") or post.get("engagement_3h")
                if eng:
                    if isinstance(eng, str):
                        eng = json.loads(eng)
                    skill_stats[skill]["total_likes"] += eng.get("likes", 0) + eng.get("like_count", 0)
                    skill_stats[skill]["total_retweets"] += eng.get("retweets", 0) + eng.get("repost_count", 0)

            lines = []
            for skill, stats in sorted(skill_stats.items(), key=lambda x: -x[1]["count"]):
                avg_likes = stats["total_likes"] / stats["count"] if stats["count"] else 0
                avg_rt = stats["total_retweets"] / stats["count"] if stats["count"] else 0
                lines.append(f"- {skill}: {stats['count']} posts, avg {avg_likes:.1f} likes, {avg_rt:.1f} retweets")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Failed to get skill engagement stats: {e}")
            return ""

    async def _generate_dynamic_queries(self, mode: str) -> list[str]:
        """Generate search queries dynamically based on current curiosity and memory."""
        # Fallback queries in case LLM fails
        fallback = self._get_fallback_queries(mode)

        try:
            curiosity = ""
            memory = ""
            if self.db:
                curiosity = await self.db.get_identity_state("curiosity")
                memory = await self.db.get_identity_state("memory")

            # If no curiosity state yet, use fallback
            if not curiosity or curiosity.startswith("龍蝦還沒"):
                return fallback

            prompt = DYNAMIC_QUERY_PROMPT.format(
                curiosity=curiosity[:500],
                memory=memory[:500],
                mode=mode,
            )
            result = await self.llm.chat_json("lobster", "", prompt)
            queries = result.get("queries", [])

            if queries and len(queries) >= 2:
                logger.info(f"Generated {len(queries)} dynamic queries for {mode}")
                return queries[:5]

        except Exception as e:
            logger.warning(f"Dynamic query generation failed, using fallback: {e}")

        return fallback

    def _get_fallback_queries(self, mode: str) -> list[str]:
        """Static fallback queries when dynamic generation fails."""
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

    async def _deep_read_url(self, url: str) -> str:
        """Read URL content with best available method: PDF → Browser → Jina."""
        # PDF detection
        if self.pdf_reader and self.pdf_reader.is_pdf_url(url):
            text = await self.pdf_reader.extract_from_url(url)
            if text:
                return text

        # Try browser (JS rendering) if available
        if self.browser and self.browser.available:
            text = await self.browser.read_page(url)
            if text and len(text) > 200:
                return text

        # Fallback to Jina
        if self.jina_reader:
            return await self.jina_reader.read(url)

        return ""

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
