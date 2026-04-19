"""digester/connect.py — REMOTE knowledge comparison.

Takes one extract + relevant knowledge clusters → asks Sonnet to compare →
stores connection_result in `connections` table.

This is the only step in the pipeline that costs real money.
"""

import logging
from datetime import datetime

from lobster.agent_logic.prompts import CONNECT_SYSTEM, CONNECT_USER
from lobster.utils.prompt_budget import compact_json, truncate_chars

logger = logging.getLogger("lobster.digester.connect")

# Per-cluster text budget when packing the knowledge context. Sonnet still
# sees the cluster id and open gaps in full; this only caps the
# current_understanding narrative.
_CLUSTER_TEXT_LIMIT = 400
_MAX_CLUSTERS = 20


class Connector:
    def __init__(self, llm, db):
        self.llm = llm
        self.db = db

    async def connect(self, extract_id: str, soul_md: str = "") -> dict | None:
        """Connect one extract to knowledge state. Returns connection dict or None."""
        extract = await self.db.get_extract(extract_id)
        if not extract:
            return None

        # Pack clusters: cap count + trim narrative so prompt stays bounded.
        clusters = await self.db.list_clusters(limit=_MAX_CLUSTERS)
        relevant = [
            {
                "id": c["id"],
                "current_understanding": truncate_chars(
                    c.get("current_understanding", ""), _CLUSTER_TEXT_LIMIT
                ),
                "open_gaps": (c.get("open_gaps") or [])[:3],
            }
            for c in clusters
        ]

        try:
            data = await self.llm.json_remote(
                agent="connect",
                system_prompt=CONNECT_SYSTEM,
                user_message=CONNECT_USER.format(
                    structured_extract_json=compact_json(extract.get("structured_data", {})),
                    relevant_clusters_json=compact_json(relevant),
                ),
                max_tokens=2048,
            )
        except Exception as e:
            logger.warning(f"remote connect failed: {e}")
            return None

        if not data or not isinstance(data, dict):
            return None

        connection_type = data.get("connection_type", "irrelevant")
        connected_clusters = data.get("connected_clusters") or []
        insight = data.get("insight", "")
        confidence = data.get("confidence", 0.0)
        new_questions = data.get("new_questions") or []

        connection_id = f"con_{extract_id.split('_', 1)[1]}_{datetime.utcnow().strftime('%H%M%S%f')}"

        try:
            await self.db.insert_connection(
                connection_id=connection_id,
                extract_id=extract_id,
                connection_type=connection_type,
                connected_clusters=connected_clusters,
                insight=insight,
                confidence=confidence,
                questions_spawned=new_questions,
            )
            if connection_type != "irrelevant":
                await self.db.bump_source_counters(extract.get("source_type", ""), connects=1)
        except Exception as e:
            logger.warning(f"db insert_connection failed: {e}")

        # Spawn new open questions
        for q in new_questions[:2]:
            try:
                await self.db.insert_open_question(
                    question=q,
                    soul_anchor=None,
                    expected_source_types=[],
                    priority=0.6,
                    reasoning=f"spawned from connection {connection_id}",
                    parent_insight_id=None,
                )
            except Exception:
                pass

        return {
            "id": connection_id,
            "extract_id": extract_id,
            "connection_type": connection_type,
            "connected_clusters": connected_clusters,
            "insight": insight,
            "confidence": confidence,
            "new_questions": new_questions,
        }
