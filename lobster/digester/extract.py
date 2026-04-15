"""digester/extract.py — source-aware structured extraction.

Takes a RawFind from any source adapter and runs the appropriate LOCAL prompt
to produce a structured extract dict. Stores it in the `extracts` table and
returns the extract id.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from lobster.agent_logic.prompts import (
    EXTRACT_SYSTEM,
    EXTRACT_PUBMED_USER,
    EXTRACT_BIORXIV_USER,
    EXTRACT_ARXIV_USER,
    EXTRACT_BLOG_USER,
    EXTRACT_TWITTER_USER,
)

logger = logging.getLogger("lobster.digester.extract")

SCHEMA_DIR = Path(__file__).parent / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


SCHEMAS = {
    "pubmed":  _load_schema("pubmed"),
    "biorxiv": _load_schema("biorxiv"),
    "arxiv":   _load_schema("arxiv"),
    "blog":    _load_schema("blog"),
    "twitter": _load_schema("twitter"),
}


def _truncate(s: str | None, n: int = 4000) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[:n] + " ..."


class Extractor:
    def __init__(self, llm, db):
        self.llm = llm
        self.db = db

    async def extract(self, raw_find) -> str | None:
        """Extract one RawFind → store in DB → return extract_id, or None on failure."""
        source = raw_find.source_type
        if source not in SCHEMAS:
            logger.warning(f"unknown source type {source}, skipping")
            return None

        # Build prompt
        try:
            user_msg = self._build_user_prompt(raw_find)
        except Exception as e:
            logger.warning(f"prompt build failed: {e}")
            return None

        try:
            data = await self.llm.json_local(
                agent=f"extract_{source}",
                system_prompt=EXTRACT_SYSTEM,
                user_message=user_msg,
                max_tokens=1500,
            )
        except Exception as e:
            logger.warning(f"local extract failed: {e}")
            return None

        if not data or not isinstance(data, dict):
            logger.warning(f"empty/non-dict extract result for {raw_find.title[:50] if raw_find.title else '?'}")
            return None

        extract_id = self._make_id(source)
        try:
            await self.db.insert_extract(
                extract_id=extract_id,
                source_type=source,
                structured_data=data,
                source_id=raw_find.source_id,
                url=raw_find.url,
                title=raw_find.title,
                one_liner=data.get("one_liner"),
            )
            await self.db.bump_source_counters(source, extracts=1)
            return extract_id
        except Exception as e:
            logger.warning(f"db insert_extract failed: {e}")
            return None

    def _build_user_prompt(self, rf) -> str:
        st = rf.source_type
        if st == "pubmed":
            return EXTRACT_PUBMED_USER.format(
                title=rf.title or "?",
                journal=rf.metadata.get("journal", "?"),
                pub_date=rf.metadata.get("pub_date", "?"),
                abstract=_truncate(rf.content or rf.metadata.get("abstract", ""), 3000),
                pmid=rf.source_id or "?",
            )
        if st == "biorxiv":
            return EXTRACT_BIORXIV_USER.format(
                title=rf.title or "?",
                authors=rf.metadata.get("authors", "?"),
                pub_date=rf.metadata.get("pub_date", "?"),
                abstract=_truncate(rf.content or rf.metadata.get("abstract", ""), 3000),
                doi=rf.source_id or rf.url or "?",
            )
        if st == "arxiv":
            return EXTRACT_ARXIV_USER.format(
                title=rf.title or "?",
                authors=rf.metadata.get("authors", "?"),
                pub_date=rf.metadata.get("pub_date", "?"),
                abstract=_truncate(rf.content or rf.metadata.get("abstract", ""), 3000),
                arxiv_id=rf.source_id or "?",
            )
        if st == "blog":
            return EXTRACT_BLOG_USER.format(
                title=rf.title or "?",
                author=rf.metadata.get("author", "?"),
                url=rf.url or "?",
                content=_truncate(rf.content, 4000),
            )
        if st == "twitter":
            return EXTRACT_TWITTER_USER.format(
                handle=rf.metadata.get("handle", "?"),
                url=rf.url or "?",
                text=_truncate(rf.content, 1000),
                engagement=rf.metadata.get("engagement", "unknown"),
            )
        raise ValueError(f"no template for source {st}")

    @staticmethod
    def _make_id(source: str) -> str:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        return f"ext_{source}_{ts}"
