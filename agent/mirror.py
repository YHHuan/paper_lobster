"""Weekly Mirror agent — Sunday night self-reflection.

Analyzes the week's performance, proposes identity adjustments,
and detects personality drift.
"""

import json
import logging
from datetime import date, timedelta

from utils.identity_loader import load_identity
from agent.prompts import MIRROR_PROMPT

logger = logging.getLogger("lobster.agent.mirror")


class Mirror:
    def __init__(self, llm, db, telegram=None):
        self.llm = llm
        self.db = db
        self.telegram = telegram

    async def weekly_reflection(self):
        """Run the full weekly reflection cycle."""
        logger.info("Starting weekly Mirror reflection")

        # Gather week's data
        weekly_data = await self._gather_weekly_data()

        # Run reflection
        identity = load_identity()
        user_msg = MIRROR_PROMPT.format(weekly_data=json.dumps(weekly_data, ensure_ascii=False))

        try:
            result = await self.llm.chat_json("mirror", identity, user_msg)

            # Send weekly report
            report = result.get("report", "No report generated")
            if self.telegram:
                await self.telegram.notify(f"🪞 Lobster Weekly Report\n\n{report}")

            # Handle proposed changes
            soul_changes = result.get("soul_changes", [])
            style_changes = result.get("style_changes", [])

            if soul_changes or style_changes:
                changes_msg = "📝 Proposed identity changes:\n\n"
                for c in soul_changes:
                    changes_msg += f"soul.md [{c.get('section')}]:\n"
                    changes_msg += f"  Reason: {c.get('reason')}\n"
                if style_changes:
                    for c in style_changes:
                        changes_msg += f"style.md [{c.get('section')}]:\n"
                        changes_msg += f"  Reason: {c.get('reason')}\n"
                changes_msg += "\nApprove via /approve_changes"

                if self.telegram:
                    await self.telegram.notify(changes_msg)

                # Log proposed evolution
                await self.db.log_evolution(
                    type="mirror_proposal",
                    description=f"Week of {date.today().isoformat()}: "
                                f"{len(soul_changes)} soul + {len(style_changes)} style changes",
                    diff_content=json.dumps(
                        {"soul": soul_changes, "style": style_changes},
                        ensure_ascii=False,
                    ),
                )

            # Check personality drift
            drift = result.get("personality_drift_score", 0)
            if drift > 6:
                logger.warning(f"Personality drift detected: {drift}/10")
                if self.telegram:
                    await self.telegram.notify(
                        f"⚠️ Personality drift: {drift}/10\n"
                        f"The lobster may be straying from its soul.md values."
                    )

            # Update curiosity directions
            directions = result.get("curiosity_directions", [])
            if directions:
                logger.info(f"New curiosity directions: {directions}")

        except Exception as e:
            logger.error(f"Weekly reflection failed: {e}")
            if self.telegram:
                await self.telegram.notify(f"❌ Mirror weekly reflection failed: {e}")

    async def _gather_weekly_data(self) -> dict:
        """Collect all data needed for weekly analysis."""
        posts = await self.db.get_recent_posts(days=7)

        # Organize by platform and skill
        by_platform = {"x": [], "threads": []}
        by_skill = {}
        by_language = {"en": 0, "zh": 0}

        for p in posts:
            platform = p.get("platform", "x")
            if platform in by_platform:
                by_platform[platform].append(p)

            skill = p.get("skill_used", "unknown")
            by_skill.setdefault(skill, []).append(p)

            lang = p.get("language", "en")
            by_language[lang] = by_language.get(lang, 0) + 1

        return {
            "total_posts": len(posts),
            "by_platform": {k: len(v) for k, v in by_platform.items()},
            "by_skill": {k: len(v) for k, v in by_skill.items()},
            "by_language": by_language,
            "posts_with_engagement": [
                {
                    "skill": p.get("skill_used"),
                    "platform": p.get("platform"),
                    "language": p.get("language"),
                    "hook_score": p.get("hook_score"),
                    "engagement_24h": p.get("engagement_24h", {}),
                    "posted_text": (p.get("posted_text") or "")[:100],
                }
                for p in posts
                if p.get("engagement_24h") and p["engagement_24h"] != "{}"
            ],
            "week_of": date.today().isoformat(),
        }

    async def analyze_engagement_patterns(self) -> dict:
        """Analyze which content patterns get the best engagement."""
        posts = await self.db.get_recent_posts(days=30)
        # Simple analysis: average engagement by skill
        skill_engagement = {}
        for p in posts:
            skill = p.get("skill_used", "unknown")
            eng = p.get("engagement_24h", {})
            if isinstance(eng, str):
                try:
                    eng = json.loads(eng)
                except Exception:
                    eng = {}
            likes = eng.get("likes", eng.get("like_count", 0))
            skill_engagement.setdefault(skill, []).append(likes)

        return {
            skill: {
                "avg_likes": sum(likes) / len(likes) if likes else 0,
                "count": len(likes),
            }
            for skill, likes in skill_engagement.items()
        }
