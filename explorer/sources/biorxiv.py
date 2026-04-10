"""bioRxiv API source adapter.

bioRxiv's public API is best for date-range listing rather than keyword search.
We do a date-range fetch and filter client-side by keyword. For better keyword
hit rates, we also fall back to a Google Scholar–style URL via Tavily if needed.
"""

import logging
from datetime import date, timedelta

import httpx

from .base import OpenQuestion, RawFind, Source

logger = logging.getLogger("lobster.sources.biorxiv")

BIORXIV_API = "https://api.biorxiv.org"


class BioRxivSource(Source):
    name = "biorxiv"

    def __init__(self, llm=None):
        self.llm = llm
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(self, question: OpenQuestion, max_results: int = 5) -> list[RawFind]:
        # Strategy: pull last 10 days of bioRxiv, filter abstracts that match
        # any keyword extracted from the question.
        end = date.today()
        start = end - timedelta(days=10)
        try:
            resp = await self.client.get(
                f"{BIORXIV_API}/details/biorxiv/{start.isoformat()}/{end.isoformat()}/0"
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"biorxiv fetch failed: {e}")
            return []

        items = data.get("collection", []) or []
        keywords = [kw.lower() for kw in self._keywords(question.question)]

        scored = []
        for it in items:
            title = (it.get("title") or "")
            abstract = (it.get("abstract") or "")
            haystack = (title + " " + abstract).lower()
            hits = sum(1 for kw in keywords if kw in haystack)
            if hits > 0:
                scored.append((hits, it))

        scored.sort(key=lambda x: x[0], reverse=True)

        out = []
        for _, it in scored[:max_results]:
            doi = it.get("doi")
            url = f"https://www.biorxiv.org/content/{doi}v{it.get('version', '1')}" if doi else None
            out.append(
                RawFind(
                    source_type="biorxiv",
                    title=it.get("title"),
                    url=url,
                    content=it.get("abstract"),
                    source_id=doi,
                    metadata={
                        "authors": it.get("authors", ""),
                        "pub_date": it.get("date", ""),
                        "abstract": it.get("abstract", ""),
                        "version": it.get("version", "1"),
                        "category": it.get("category", ""),
                    },
                )
            )
        return out

    @staticmethod
    def _keywords(question: str) -> list[str]:
        # Naive: split on whitespace, drop short stop-y words. The LLM-driven
        # query refinement could plug in here later.
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "are", "is", "was",
            "of", "to", "in", "on", "at", "a", "an", "by", "as", "or", "but",
            "有", "沒", "的", "在", "跟", "用", "讓", "對", "了", "我", "你",
        }
        words = [w.strip(".,?!:;()[]\"'") for w in question.split()]
        return [w for w in words if len(w) > 2 and w.lower() not in stop][:8]

    async def close(self):
        await self.client.aclose()
