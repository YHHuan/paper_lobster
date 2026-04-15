"""digester/connect.py — REMOTE knowledge comparison.

Takes one extract + relevant knowledge clusters → asks Sonnet to compare →
stores connection_result in `connections` table.

This is the only step in the pipeline that costs real money.
"""

import json
import logging
from datetime import datetime

from lobster.agent_logic.prompts import CONNECT_SYSTEM, CONNECT_USER

logger = logging.getLogger("lobster.digester.connect")


class Connector:
    def __init__(self, llm, db):
        self.llm = llm
        self.db = db

    async def connect(self, extract_id: str, soul_md: str = "") -> dict | None:
        """Connect one extract to knowledge state. Returns connection dict or None."""
        extract = await self.db.get_extract(extract_id)
        if not extract:
            return None

        # Get relevant clusters — we feed all clusters in for the LLM to
        # decide which are relevant. For 30+ clusters this could grow,
        # but Sonnet's context handles it fine for now.
        clusters = await self.db.list_clusters(limit=30)
        relevant = [
            {
                "id": c["id"],
                "current_understanding": c.get("current_understanding", ""),
                "open_gaps": c.get("open_gaps", []),
            }
            for c in clusters
        ]

        try:
            data = await self.llm.json_remote(
                agent="connect",
                system_prompt=CONNECT_SYSTEM,
                user_message=CONNECT_USER.format(
                    structured_extract_json=json.dumps(extract.get("structured_data", {}), ensure_ascii=False, indent=2),
                    relevant_clusters_json=json.dumps(relevant, ensure_ascii=False, indent=2),
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
