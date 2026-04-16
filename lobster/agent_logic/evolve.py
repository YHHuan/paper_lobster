"""agent/evolve.py — weekly evolution proposals (v3 NEW).

Once a week, look at:
  - source connect rates over 7d / 30d
  - new vs deprecated topics (clusters that haven't been touched)
  - human approve/reject signals on insights

Produce 0-3 proposals per type:
  1. SourceQualityUpdate — adjust source weight
  2. FrontierProposal    — suggest a new exploration frontier (added to soul.md)
  3. DeprecationProposal — flag a stale keyword

Each proposal is stored in `evolution_proposals` table and pushed to Telegram
with inline keyboard for approve/reject.
"""

import json
import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from lobster.agent_logic.prompts import EVOLVE_SYSTEM, EVOLVE_USER

logger = logging.getLogger("lobster.agent.evolve")


PROMPT_OVERRIDE_SYSTEM = """You are analyzing the lobster's recent social media posts to identify style / hook / angle patterns that drive engagement.

You will be given: a set of TOP posts (high engagement_72h) and a set of BOTTOM posts (low engagement_72h), each with platform, skill, language, hook_score, and the posted text.

Your job: for each of the four roles in the pipeline (WRITER, EDITOR, CRITIC, HOOK), produce a concise delta prompt (≤200 chars each) that would push future posts toward the TOP pattern and away from the BOTTOM pattern.

Rules — any violation means your output is rejected:
1. Ground every observation in a specific post_id from the input. No generic advice like "write more interesting posts".
2. If the top/bottom difference is noise (e.g. nothing substantive differs), return an empty string for that role's override. Do not fabricate.
3. Writer delta = how to phrase hooks / pick framings / what to emphasize.
4. Editor delta = what to cut / preserve during revision.
5. Critic delta = additional failure modes to flag beyond the default rubric.
6. Hook delta = stricter or different criteria for scoring hooks.

Respond strictly in JSON:
{
  "diff_rationale": "1-2 sentences describing the actual pattern difference you observed, citing post_ids",
  "writer": "delta prompt or empty string",
  "editor": "delta prompt or empty string",
  "critic": "delta prompt or empty string",
  "hook":   "delta prompt or empty string"
}"""


PROMPT_OVERRIDE_USER = """TOP posts (high engagement_72h):
{top_posts}

BOTTOM posts (low engagement_72h):
{bottom_posts}

Overall context:
- window: last {window_days} days
- total posts analyzed: {total_posts}
- top baseline engagement (mean): {top_baseline:.2f}
- bottom baseline engagement (mean): {bottom_baseline:.2f}

Produce the JSON."""


@dataclass
class SourceQualityUpdate:
    source: str
    current_weight: float
    proposed_weight: float
    reason: str


@dataclass
class FrontierProposal:
    topic: str
    evidence: list[str]
    proposed_keywords: list[str]


@dataclass
class DeprecationProposal:
    keyword: str
    last_connect_date: str
    reason: str


class Evolver:
    def __init__(self, llm, db, telegram=None):
        self.llm = llm
        self.db = db
        self.telegram = telegram

    async def run_weekly(self) -> dict:
        logger.info("Starting weekly evolve")
        stats = await self._gather_stats()

        try:
            data = await self.llm.json_local(
                agent="evolve",
                system_prompt=EVOLVE_SYSTEM,
                user_message=EVOLVE_USER.format(**stats),
                max_tokens=2000,
            )
        except Exception as e:
            logger.warning(f"evolve llm call failed: {e}")
            return {"status": "failed", "error": str(e)}

        if not isinstance(data, dict):
            return {"status": "failed", "error": "non-dict response"}

        sq = data.get("source_quality") or []
        nf = data.get("new_frontiers") or []
        dp = data.get("deprecations") or []

        # Trim per spec: max 3 frontiers, max 2 deprecations
        nf = nf[:3]
        dp = dp[:2]

        await self._persist_proposals("source_quality", sq)
        await self._persist_proposals("frontier", nf)
        await self._persist_proposals("deprecation", dp)

        await self._notify(sq, nf, dp)

        return {"status": "ok", "source_quality": sq, "new_frontiers": nf, "deprecations": dp}

    async def _persist_proposals(self, type_: str, items: list[dict]):
        for item in items:
            try:
                await self.db.insert_proposal(type=type_, proposal=item)
            except Exception as e:
                logger.warning(f"persist {type_} proposal failed: {e}")

    async def apply_source_quality(self, proposal: dict):
        """Called after user approves a source_quality proposal."""
        source = proposal.get("source")
        weight = float(proposal.get("proposed_weight", 0.5))
        if source:
            await self.db.update_source_weight(source, weight)

    # ── P1: outcome-gated prompt override (dry-run in W1) ──

    async def run_prompt_override(
        self,
        *,
        window_days: int = 14,
        min_samples_per_side: int = 5,
        activate: bool = False,
    ) -> dict:
        """Diff top vs bottom engagement posts → propose writer/editor/critic/hook overrides.

        Runs as dry_run by default (W1 plan). Pass activate=True once W2 window
        opens. Uses local gpt-oss-120b for the diff step (see Locked decisions).
        """
        posts = await self._load_posts_with_engagement(window_days=window_days)
        ranked = self._rank_by_engagement(posts)
        if len(ranked) < min_samples_per_side * 2:
            logger.info(
                f"prompt_override: only {len(ranked)} posts with engagement_72h — "
                f"need {min_samples_per_side*2}; skipping"
            )
            return {"status": "skipped", "reason": "insufficient_samples", "count": len(ranked)}

        top_cut = max(min_samples_per_side, len(ranked) // 10)
        top = ranked[:top_cut]
        bottom = ranked[-top_cut:]

        top_baseline = statistics.mean(p["_score"] for p in top) if top else 0.0
        bottom_baseline = statistics.mean(p["_score"] for p in bottom) if bottom else 0.0
        overall_baseline = statistics.mean(p["_score"] for p in ranked) if ranked else 0.0

        # Ask gpt-oss-120b for the diff
        # Temporarily pin the local model for this call only
        prior_model = self.llm.local.model if hasattr(self.llm, "local") else None
        try:
            if hasattr(self.llm, "local"):
                cached = self.llm.local.get_cached_models()
                if "gpt-oss-120b" in cached:
                    self.llm.local.set_model("gpt-oss-120b")

            try:
                payload = await self.llm.json_local(
                    agent="prompt_override",
                    system_prompt=PROMPT_OVERRIDE_SYSTEM,
                    user_message=PROMPT_OVERRIDE_USER.format(
                        top_posts=_format_posts(top),
                        bottom_posts=_format_posts(bottom),
                        window_days=window_days,
                        total_posts=len(ranked),
                        top_baseline=top_baseline,
                        bottom_baseline=bottom_baseline,
                    ),
                    max_tokens=1500,
                )
            except Exception as e:
                logger.warning(f"prompt_override llm call failed: {e}")
                return {"status": "failed", "error": str(e)}
        finally:
            if prior_model and hasattr(self.llm, "local"):
                self.llm.local.set_model(prior_model)

        if not isinstance(payload, dict):
            return {"status": "failed", "error": "non-dict response"}

        diff_rationale = payload.get("diff_rationale", "")
        derived_from = {
            "top_post_ids": [str(p["id"]) for p in top],
            "bottom_post_ids": [str(p["id"]) for p in bottom],
            "window_days": window_days,
            "diff_rationale": diff_rationale,
        }

        proposed_status = "active" if activate else "dry_run"
        created: list[dict] = []
        for target in ("writer", "editor", "critic", "hook"):
            content = (payload.get(target) or "").strip()
            if not content:
                logger.info(f"prompt_override: {target} skipped (empty delta)")
                continue
            row = await self.db.insert_prompt_override(
                target=target,
                content=content,
                derived_from=derived_from,
                variant="B",
                status=proposed_status,
                baseline_engagement=overall_baseline,
                notes=None,
            )
            created.append(row)

        if self.telegram:
            lines = [
                f"🧪 Prompt Override { 'proposed (dry-run)' if not activate else 'activated' }",
                f"Window: last {window_days}d, {len(ranked)} scored posts",
                f"Top baseline mean: {top_baseline:.1f} | bottom: {bottom_baseline:.1f}",
                "",
                f"Rationale: {diff_rationale[:250]}",
                "",
            ]
            if created:
                lines.append("Drafted deltas:")
                for row in created:
                    lines.append(f"  • {row['target']} v{row['version']} variant {row['variant']}")
                if not activate:
                    ids = ", ".join(r["id"] for r in created)
                    lines.append(f"\nActivate: /activate_override <id>  (ids: {ids[:200]})")
            else:
                lines.append("(no target had a substantive delta — nothing stored)")
            try:
                await self.telegram.notify("\n".join(lines))
            except Exception:
                pass

        return {
            "status": "ok",
            "created": created,
            "diff_rationale": diff_rationale,
            "top_baseline": top_baseline,
            "bottom_baseline": bottom_baseline,
            "scored_posts": len(ranked),
        }

    async def _load_posts_with_engagement(self, *, window_days: int) -> list[dict]:
        posts = await self.db.get_recent_posts(days=window_days)
        kept = []
        for p in posts:
            eng = p.get("engagement_72h")
            if not eng or eng == "{}":
                continue
            if isinstance(eng, str):
                try:
                    eng = json.loads(eng)
                except Exception:
                    continue
            if not isinstance(eng, dict) or not eng:
                continue
            score = (
                (eng.get("like_count") or 0)
                + (eng.get("reply_count") or 0)
                + (eng.get("retweet_count") or 0)
                + (eng.get("quote_count") or 0)
                + (eng.get("likes") or 0)
                + (eng.get("replies") or 0)
            )
            if score <= 0:
                continue
            p["_score"] = float(score)
            p["_engagement_parsed"] = eng
            kept.append(p)
        return kept

    @staticmethod
    def _rank_by_engagement(posts: list[dict]) -> list[dict]:
        return sorted(posts, key=lambda p: p["_score"], reverse=True)

    async def _gather_stats(self) -> dict:
        loop_stats = await self.db.get_recent_loop_stats(days=7)
        source_weights = await self.db.get_source_weights_full()

        # connect rates by source for the prompt
        rate_lines = []
        for sw in source_weights:
            cr_7d = sw.get("connect_rate_7d")
            if cr_7d is None:
                # compute on-the-fly
                try:
                    cr_7d = await self.db.get_connection_rate(sw["source"], days=7)
                except Exception:
                    cr_7d = 0.0
            rate_lines.append(
                f"  {sw['source']}: weight={sw.get('weight', 0):.2f}, "
                f"connect_rate_7d={cr_7d:.2f}, "
                f"total_extracts={sw.get('total_extracts', 0)}, "
                f"total_connects={sw.get('total_connects', 0)}"
            )
        source_rates = "\n".join(rate_lines)

        recent_insights = await self.db.get_recent_insights(days=7, limit=50)
        approved = [i for i in recent_insights if (i.get("human_rating") or 0) >= 4]
        rejected = [i for i in recent_insights if (i.get("human_rating") or 0) and i.get("human_rating", 5) <= 2]

        clusters = await self.db.list_clusters(limit=50)
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        new_clusters = [c["id"] for c in clusters if (c.get("created_at") or "") >= week_ago]
        updated_clusters = [c["id"] for c in clusters if (c.get("updated_at") or "") >= week_ago and c["id"] not in new_clusters]

        return {
            "total_loops": loop_stats.get("total_loops", 0),
            "total_extracts": loop_stats.get("extracts_produced", 0),
            "source_connect_rates": source_rates or "  (no source data)",
            "new_clusters": ", ".join(new_clusters) or "(none)",
            "updated_clusters": ", ".join(updated_clusters) or "(none)",
            "approved_insights": ", ".join(i["id"] for i in approved[:10]) or "(none)",
            "rejected_insights": ", ".join(i["id"] for i in rejected[:10]) or "(none)",
            "manual_explores": "(see open_questions table)",
            "urls_shared": "(see open_questions table)",
        }

    async def _notify(self, sq: list[dict], nf: list[dict], dp: list[dict]):
        if not self.telegram:
            return
        if not (sq or nf or dp):
            try:
                await self.telegram.notify("🧬 Evolve: 本週沒有夠強的提案，maintain status quo。")
            except Exception:
                pass
            return

        parts = ["🧬 Evolution Proposals (週報)\n"]
        if sq:
            parts.append("📈 Source Quality")
            for s in sq:
                parts.append(
                    f"  {s.get('source')}: {s.get('current_weight', '?')} → {s.get('proposed_weight', '?')} "
                    f"({s.get('reason', '')})"
                )
        if nf:
            parts.append("\n🆕 New Frontier")
            for f in nf:
                parts.append(f'  "{f.get("topic", "?")}"  evidence={f.get("evidence", [])}')
        if dp:
            parts.append("\n🗑️ Deprecation")
            for d in dp:
                parts.append(f"  {d.get('keyword')} — {d.get('reason', '')}")
        parts.append("\n用 /evolve 看完整 JSON，approve/reject via reply.")
        try:
            await self.telegram.notify("\n".join(parts))
        except Exception:
            pass


def _format_posts(posts: list[dict]) -> str:
    lines = []
    for p in posts:
        text = (p.get("posted_text") or p.get("draft_text") or "")[:400]
        lines.append(
            f"- post_id={p.get('id')} platform={p.get('platform')} "
            f"lang={p.get('language')} skill={p.get('skill_used')} "
            f"hook={p.get('hook_score')} eng_score={p.get('_score'):.1f}\n"
            f"  text: {text}"
        )
    return "\n".join(lines) if lines else "(none)"
