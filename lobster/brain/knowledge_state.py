"""brain/knowledge_state.py — CRUD for the lobster's brain.

Knowledge state lives in two places:

1. Postgres `knowledge_clusters` table (canonical, queried by Connect)
2. Optional `data/knowledge_state.json` mirror for fast local read + git-friendly diff

Both are kept in sync. JSON is opt-in via env KNOWLEDGE_STATE_PATH; if unset,
DB is the only store.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("lobster.brain.knowledge")


class KnowledgeState:
    def __init__(self, db, json_path: str | None = None):
        self.db = db
        self.json_path = Path(json_path) if json_path else None
        if self.json_path and not self.json_path.exists():
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            self.json_path.write_text(json.dumps({"clusters": {}, "meta": {}}, indent=2))

    async def upsert_cluster(
        self,
        cluster_id: str,
        current_understanding: str,
        *,
        confidence: float = 0.5,
        key_sources: list[str] | None = None,
        open_gaps: list[str] | None = None,
        related_clusters: list[str] | None = None,
    ):
        await self.db.upsert_cluster(
            cluster_id=cluster_id,
            current_understanding=current_understanding,
            confidence=confidence,
            key_sources=key_sources,
            open_gaps=open_gaps,
            related_clusters=related_clusters,
        )
        if self.json_path:
            self._mirror_to_json(cluster_id, {
                "current_understanding": current_understanding,
                "confidence": confidence,
                "key_sources": key_sources or [],
                "open_gaps": open_gaps or [],
                "related_clusters": related_clusters or [],
                "updated_at": datetime.utcnow().isoformat(),
            })

    async def get_cluster(self, cluster_id: str) -> dict | None:
        return await self.db.get_cluster(cluster_id)

    async def list_clusters(self, limit: int = 50) -> list[dict]:
        return await self.db.list_clusters(limit=limit)

    async def summary_text(self) -> str:
        return await self.db.get_clusters_summary()

    def _mirror_to_json(self, cluster_id: str, data: dict):
        try:
            blob = json.loads(self.json_path.read_text())
            blob.setdefault("clusters", {})[cluster_id] = data
            blob.setdefault("meta", {})
            blob["meta"]["last_major_update"] = datetime.utcnow().isoformat()
            blob["meta"]["total_clusters"] = len(blob["clusters"])
            self.json_path.write_text(json.dumps(blob, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"json mirror failed: {e}")
