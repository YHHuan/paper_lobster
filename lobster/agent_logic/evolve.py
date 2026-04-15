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
from dataclasses import dataclass
from datetime import datetime, timedelta

from lobster.agent_logic.prompts import EVOLVE_SYSTEM, EVOLVE_USER

logger = logging.getLogger("lobster.agent.evolve")


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
