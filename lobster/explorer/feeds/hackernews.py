"""Hacker News Firebase API explorer."""

import asyncio
import logging
from typing import AsyncIterator

import httpx

from .base import BaseFeedExplorer, RawDiscovery

logger = logging.getLogger("lobster.explorer.feeds.hackernews")

BASE_URL = "https://hacker-news.firebaseio.com/v0"


class HackerNewsExplorer(BaseFeedExplorer):
    name = "hackernews"

    async def fetch(self, config: dict) -> AsyncIterator[RawDiscovery]:
        hn = config.get("hackernews") or {}
        if not hn.get("enabled"):
            return
        modes = hn.get("modes") or []
        priority_kw = [k.lower() for k in hn.get("priority_keywords") or []]

        async with httpx.AsyncClient(timeout=30.0) as client:
            for mode_cfg in modes:
                mode = mode_cfg.get("type")
                if not mode:
                    continue
                async for item in self._fetch_mode(client, mode, mode_cfg, priority_kw):
                    yield item

    async def _fetch_mode(
        self,
        client: httpx.AsyncClient,
        mode: str,
        mode_cfg: dict,
        priority_kw: list[str],
    ) -> AsyncIterator[RawDiscovery]:
        max_items = int(mode_cfg.get("max_items", 30))
        min_score = int(mode_cfg.get("min_score", 100))

        try:
            ids_resp = await client.get(f"{BASE_URL}/{mode}stories.json")
            ids_resp.raise_for_status()
            ids = (ids_resp.json() or [])[:max_items]
        except Exception as e:
            logger.warning(f"hn list {mode} failed: {e}")
            return

        sem = asyncio.Semaphore(5)

        async def _fetch_item(item_id):
            async with sem:
                try:
                    r = await client.get(f"{BASE_URL}/item/{item_id}.json")
                    r.raise_for_status()
                    return r.json()
                except Exception as e:
                    logger.debug(f"hn item {item_id} failed: {e}")
                    return None

        items = await asyncio.gather(*[_fetch_item(i) for i in ids])

        for item in items:
            if not item or item.get("type") != "story":
                continue
            score = int(item.get("score") or 0)
            title = (item.get("title") or "").strip()
            if not title:
                continue

            effective_min = min_score
            if priority_kw and any(kw in title.lower() for kw in priority_kw):
                effective_min = max(1, min_score // 2)
            if score < effective_min:
                continue

            link = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}"
            text = item.get("text") or title
            yield RawDiscovery(
                source_type="hn",
                source_name="Hacker News",
                url=link,
                title=title,
                raw_text=text[:500],
                language="en",
                metadata={
                    "score": score,
                    "comments": int(item.get("descendants") or 0),
                    "author": item.get("by", ""),
                    "hn_id": item.get("id"),
                },
            )
