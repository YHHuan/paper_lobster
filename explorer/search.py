"""Tavily Search API client.

Free tier: 1000 searches/month. Used for discovery exploration.
"""

import os
import logging

import httpx

logger = logging.getLogger("lobster.explorer.search")

TAVILY_API = "https://api.tavily.com"


class TavilySearch:
    def __init__(self):
        self.api_key = os.environ.get("TAVILY_API_KEY", "")
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = False,
    ) -> list[dict]:
        """Search the web via Tavily.

        Args:
            query: Search query.
            max_results: Number of results (default 5).
            search_depth: "basic" or "advanced" (costs 2 credits).
            include_answer: Whether to include AI-generated answer.

        Returns:
            List of {title, url, content, score} dicts.
        """
        if not self.api_key:
            logger.warning("TAVILY_API_KEY not set, skipping search")
            return []

        try:
            resp = await self.client.post(
                f"{TAVILY_API}/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": search_depth,
                    "include_answer": include_answer,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0),
                })

            logger.info(f"Tavily search '{query[:50]}' → {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return []

    async def close(self):
        await self.client.aclose()
