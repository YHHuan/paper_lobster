"""explorer/forage.py — question-driven multi-source search.

Takes a list of OpenQuestions, deterministically routes each to source
adapters based on `expected_source_types` and keyword heuristics, runs them
in parallel, and returns RawFinds for the digester to chew on.
"""

import asyncio
import logging

from .sources.base import OpenQuestion, RawFind, Source
from .sources.pubmed import PubMedSource
from .sources.biorxiv import BioRxivSource
from .sources.arxiv import ArXivSource
from .sources.tavily import TavilySource
from .sources.jina import JinaSource

logger = logging.getLogger("lobster.forage")


CLINICAL_KEYWORDS = (
    "trial", "rct", "cohort", "intervention", "disease", "treatment", "patient",
    "clinical", "epidemiology", "mortality", "incidence", "prevalence", "risk",
    "臨床", "病人", "治療", "介入", "世代", "風險",
)

PREPRINT_KEYWORDS = (
    "preprint", "model", "architecture", "benchmark", "transformer", "agent",
    "neural", "deep learning", "llm", "embedding",
)

WEB_KEYWORDS = (
    "trend", "opinion", "take", "thread", "newsletter", "blog", "substack",
    "意見", "趨勢",
)


class Forager:
    """Orchestrator. Holds a long-lived pool of source instances."""

    def __init__(self, llm=None, db=None):
        self.llm = llm
        self.db = db
        self.sources: dict[str, Source] = {
            "pubmed":  PubMedSource(llm),
            "biorxiv": BioRxivSource(llm),
            "arxiv":   ArXivSource(llm),
            "tavily":  TavilySource(llm),
            "jina":    JinaSource(llm),
        }

    @staticmethod
    def route_question(q: OpenQuestion) -> list[str]:
        """Deterministic routing → list of source names."""
        chosen: list[str] = []
        text = q.question.lower()
        expected = [s.lower() for s in (q.expected_source_types or [])]

        for name in ("pubmed", "biorxiv", "arxiv", "tavily", "jina"):
            if name in expected:
                chosen.append(name)

        # Keyword fallbacks
        if any(k in text for k in CLINICAL_KEYWORDS):
            if "pubmed" not in chosen:
                chosen.append("pubmed")
        if any(k in text for k in PREPRINT_KEYWORDS):
            if "arxiv" not in chosen:
                chosen.append("arxiv")
            if "biorxiv" not in chosen:
                chosen.append("biorxiv")
        if any(k in text for k in WEB_KEYWORDS):
            if "tavily" not in chosen:
                chosen.append("tavily")

        # Default: pubmed for any clinical-sounding question
        if not chosen:
            chosen = ["pubmed", "arxiv"]

        return chosen

    async def forage_question(self, q: OpenQuestion, max_per_source: int = 3) -> list[RawFind]:
        names = self.route_question(q)
        logger.info(f"Forage q='{q.question[:60]}...' → sources={names}")

        # Filter by source weight if DB available — drop sources with weight < 0.2
        if self.db:
            try:
                weights = await self.db.get_source_weights()
                names = [n for n in names if weights.get(n, 0.5) >= 0.2]
            except Exception as e:
                logger.warning(f"could not fetch source weights: {e}")

        if not names:
            return []

        async def _go(name):
            try:
                return await self.sources[name].search(q, max_results=max_per_source)
            except Exception as e:
                logger.warning(f"source {name} failed: {e}")
                return []

        results = await asyncio.gather(*[_go(n) for n in names])

        all_finds: list[RawFind] = []
        seen_urls = set()
        for batch in results:
            for f in batch:
                if f.url and f.url in seen_urls:
                    continue
                if f.url:
                    seen_urls.add(f.url)
                all_finds.append(f)

        logger.info(f"Forage q='{q.question[:60]}...' → {len(all_finds)} unique finds")
        return all_finds

    async def forage_url(self, url: str, *, title: str | None = None) -> RawFind | None:
        """Manual URL injection — runs Jina to read full content."""
        return await self.sources["jina"].read_url(url, title=title)

    async def close(self):
        for s in self.sources.values():
            try:
                await s.close()
            except Exception:
                pass
