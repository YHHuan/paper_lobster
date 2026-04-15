"""Tavily web search source adapter (for blog / web finds)."""

import os
import logging

import httpx

from .base import OpenQuestion, RawFind, Source

logger = logging.getLogger("lobster.sources.tavily")

TAVILY_API = "https://api.tavily.com"


class TavilySource(Source):
    name = "tavily"

    def __init__(self, llm=None):
        self.llm = llm
        self.api_key = os.environ.get("TAVILY_API_KEY", "")
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(self, question: OpenQuestion, max_results: int = 5) -> list[RawFind]:
        if not self.api_key:
            logger.warning("TAVILY_API_KEY not set, skipping")
            return []
        try:
            resp = await self.client.post(
                f"{TAVILY_API}/search",
                json={
                    "api_key": self.api_key,
                    "query": question.question,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"tavily search failed: {e}")
            return []

        out = []
        for r in data.get("results", []):
            url = r.get("url", "")
            out.append(
                RawFind(
                    source_type="blog",
                    title=r.get("title", ""),
                    url=url,
                    content=r.get("content", ""),
                    source_id=url,
                    metadata={"score": r.get("score", 0), "author": ""},
                )
            )
        return out

    async def close(self):
        await self.client.aclose()
