"""digester/synthesize.py — connection results → insights + new questions.

LOCAL tier. Takes a list of connections from one loop iteration and decides
what (if anything) is worth surfacing as an insight to Salmon.
"""

import json
import logging
from datetime import datetime

from agent.prompts import SYNTHESIZE_SYSTEM, SYNTHESIZE_USER

logger = logging.getLogger("lobster.digester.synthesize")


def _extract_active_projects(soul_md: str) -> str:
    """Pluck the Active Projects block from soul.md."""
    lines = soul_md.splitlines()
    out = []
    in_block = False
    for line in lines:
        if line.strip().startswith("### 正在跑的研究") or line.strip().startswith("## Active Projects"):
            in_block = True
            continue
        if in_block:
            if line.startswith("### ") or line.startswith("## "):
                break
            if line.strip():
                out.append(line)
    return "\n".join(out) if out else "(no active projects parsed)"


class Synthesizer:
    def __init__(self, llm, db):
        self.llm = llm
        self.db = db

    async def synthesize(self, connections: list[dict], soul_md: str = "") -> list[dict]:
        """Returns list of inserted insight dicts. Empty if none worth surfacing."""
        if not connections:
            return []

        # Filter out irrelevant
        useful = [c for c in connections if c.get("connection_type") != "irrelevant"]
        if not useful:
            return []

        try:
            data = await self.llm.json_local(
                agent="synthesize",
                system_prompt=SYNTHESIZE_SYSTEM,
                user_message=SYNTHESIZE_USER.format(
                    connections_json=json.dumps(useful, ensure_ascii=False, indent=2)[:6000],
                    active_projects=_extract_active_projects(soul_md),
                ),
                max_tokens=3000,
            )
        except Exception as e:
            logger.warning(f"synthesize llm call failed: {e}")
            return []

        # The prompt asks for a JSON array
        items = data if isinstance(data, list) else (data.get("insights") if isinstance(data, dict) else [])
        if not items:
            return []

        out = []
        for item in items[:3]:
            insight_id = f"ins_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
            try:
                await self.db.insert_insight(
                    insight_id=insight_id,
                    type=item.get("type", "connection"),
                    title=item.get("title", "(untitled)"),
                    body=item.get("body", ""),
                    soul_relevance=item.get("soul_relevance") or [],
                    publishable=bool(item.get("publishable", False)),
                    hook_score=item.get("hook_score"),
                    source_extracts=item.get("source_extracts") or [],
                )
            except Exception as e:
                logger.warning(f"insert_insight failed: {e}")
                continue
            item["id"] = insight_id
            out.append(item)

            # Spawn new questions from synthesizer
            for q in (item.get("spawned_questions") or [])[:2]:
                try:
                    await self.db.insert_open_question(
                        question=q,
                        soul_anchor=(item.get("soul_relevance") or [None])[0],
                        expected_source_types=[],
                        priority=0.7,
                        reasoning=f"spawned from insight {insight_id}",
                        parent_insight_id=insight_id,
                    )
                except Exception:
                    pass

        return out
