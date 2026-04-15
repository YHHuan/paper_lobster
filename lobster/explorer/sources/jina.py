"""Jina Reader source adapter — pulls full-text for a given URL.

Used as a follow-up to Tavily when we want the full body of a Substack /
blog post for a deeper extract. Free.
"""

import logging
import httpx

from .base import OpenQuestion, RawFind, Source

logger = logging.getLogger("lobster.sources.jina")

JINA_READER = "https://r.jina.ai"


class JinaSource(Source):
    name = "jina"

    def __init__(self, llm=None):
        self.llm = llm
        self.client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    async def search(self, question: OpenQuestion, max_results: int = 5) -> list[RawFind]:
        """Jina Reader is URL-based, not search-based. This is a no-op for
        question-based queries — call `read_url()` directly when you have a URL."""
        return []

    async def read_url(self, url: str, *, title: str | None = None) -> RawFind | None:
        try:
            resp = await self.client.get(f"{JINA_READER}/{url}", headers={"Accept": "text/markdown"})
            resp.raise_for_status()
            text = resp.text
        except Exception as e:
            logger.error(f"jina read failed for {url}: {e}")
            return None

        # First non-empty line is usually title
        if not title:
            for line in text.splitlines():
                line = line.strip().lstrip("#").strip()
                if line:
                    title = line[:200]
                    break

        return RawFind(
            source_type="blog",
            title=title or "(no title)",
            url=url,
            content=text[:8000],
            source_id=url,
            metadata={"author": ""},
        )

    async def close(self):
        await self.client.aclose()
