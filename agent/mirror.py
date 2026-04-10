"""Weekly Mirror agent — Sunday night self-reflection (v3 upgraded inputs).

v2.5 input was just engagement metrics. v3 also feeds in:
  - digest_logs (recent extracts + insights)
  - knowledge_state diff (new + updated clusters this week)
  - source connect rates (7d)
  - loop_stats (rounds, empty rounds, questions resolved)
  - human_interactions

The MIRROR_PROMPT format string still treats `weekly_data` as one JSON blob, so
everything new is just nested keys.
"""

import json
import logging
from datetime import date

from utils.identity_loader import load_identity
from agent.prompts import MIRROR_PROMPT

logger = logging.getLogger("lobster.agent.mirror")


class Mirror:
    def __init__(self, llm, db, telegram=None, evolver=None):
        self.llm = llm
        self.db = db
        self.telegram = telegram
        self.evolver = evolver  # optional v3 Evolver — runs after mirror

    async def weekly_reflection(self):
        logger.info("Starting weekly Mirror reflection (v3)")

        weekly_data = await self._gather_weekly_data()

        identity = await load_identity(self.db)
        user_msg = MIRROR_PROMPT.format(weekly_data=json.dumps(weekly_data, ensure_ascii=False))

        try:
            result = await self.llm.json_remote("mirror", identity, user_msg, max_tokens=3500)

            report = result.get("report", "No report generated")
            if self.telegram:
                await self.telegram.notify(f"🪞 Lobster Weekly Report\n\n{report}")

            soul_changes = result.get("soul_changes", [])
            style_changes = result.get("style_changes", [])

            if soul_changes or style_changes:
                changes_msg = "📝 Proposed identity changes:\n\n"
                for c in soul_changes:
                    changes_msg += f"soul.md [{c.get('section')}]:\n  Reason: {c.get('reason')}\n"
                for c in style_changes:
                    changes_msg += f"style.md [{c.get('section')}]:\n  Reason: {c.get('reason')}\n"
                changes_msg += "\nApprove via /approve_changes"
                if self.telegram:
                    await self.telegram.notify(changes_msg)
                await self.db.log_evolution(
                    type="mirror_proposal",
                    description=f"Week of {date.today().isoformat()}: "
                                f"{len(soul_changes)} soul + {len(style_changes)} style changes",
                    diff_content=json.dumps(
                        {"soul": soul_changes, "style": style_changes},
                        ensure_ascii=False,
                    ),
                )

            drift = result.get("personality_drift_score", 0)
            if drift > 6 and self.telegram:
                await self.telegram.notify(
                    f"⚠️ Personality drift: {drift}/10\n"
                    f"The lobster may be straying from its soul.md values."
                )

        except Exception as e:
            logger.error(f"Weekly reflection failed: {e}")
            if self.telegram:
                await self.telegram.notify(f"❌ Mirror weekly reflection failed: {e}")

        # v3: chain into Evolve proposals
        if self.evolver:
            try:
                await self.evolver.run_weekly()
            except Exception as e:
                logger.warning(f"Evolver failed in mirror chain: {e}")

    async def _gather_weekly_data(self) -> dict:
        # v2.5 inputs ─────────────────────────────────────────
        posts = await self.db.get_recent_posts(days=7)

        by_platform = {"x": 0, "threads": 0}
        by_skill: dict = {}
        by_language = {"en": 0, "zh": 0}
        for p in posts:
            by_platform[p.get("platform", "x")] = by_platform.get(p.get("platform", "x"), 0) + 1
            by_skill[p.get("skill_used", "unknown")] = by_skill.get(p.get("skill_used", "unknown"), 0) + 1
            by_language[p.get("language", "en")] = by_language.get(p.get("language", "en"), 0) + 1

        engagement_samples = [
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
        ]

        # v3 additions ────────────────────────────────────────
        digest_summary = await self.db.get_recent_digest_summary(days=7)
        loop_stats = await self.db.get_recent_loop_stats(days=7)
        source_weights = await self.db.get_source_weights_full()
        connect_rates = {}
        for sw in source_weights:
            connect_rates[sw["source"]] = {
                "weight": sw.get("weight"),
                "connect_rate_7d": sw.get("connect_rate_7d"),
                "total_extracts": sw.get("total_extracts"),
                "total_connects": sw.get("total_connects"),
            }

        recent_insights = await self.db.get_recent_insights(days=7)
        publishable = [i for i in recent_insights if i.get("publishable")]

        return {
            # v2.5
            "week_of": date.today().isoformat(),
            "engagement": {
                "total_posts": len(posts),
                "by_platform": by_platform,
                "by_skill": by_skill,
                "by_language": by_language,
                "samples": engagement_samples,
            },
            # v3
            "digest_logs": digest_summary,
            "loop_stats": loop_stats,
            "connect_rates": connect_rates,
            "insights_this_week": {
                "total": len(recent_insights),
                "publishable": len(publishable),
                "by_type": _count_by(recent_insights, "type"),
            },
        }


def _count_by(rows: list[dict], key: str) -> dict:
    out = {}
    for r in rows:
        v = r.get(key, "?")
        out[v] = out.get(v, 0) + 1
    return out
