"""Reddit JSON API explorer.

No OAuth — relies on the public .json endpoints. A descriptive User-Agent is
mandatory; without it Reddit answers 403/429 quickly.
"""

import asyncio
import logging
import time
from typing import AsyncIterator

import httpx

from .base import BaseFeedExplorer, RawDiscovery

logger = logging.getLogger("lobster.explorer.feeds.reddit")

HEADERS = {"User-Agent": "Lobster/4.0 (personal research bot; +contact-via-owner)"}


class RedditExplorer(BaseFeedExplorer):
    name = "reddit"
    BASE_URL = "https://www.reddit.com"

    async def fetch(self, config: dict) -> AsyncIterator[RawDiscovery]:
        subreddits = config.get("subreddits") or []
        settings = config.get("fetch_settings") or {}
        pause = float(settings.get("request_pause_seconds", 2))

        async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
            for sub_cfg in subreddits:
                async for item in self._fetch_sub(client, sub_cfg, settings):
                    yield item
                await asyncio.sleep(pause)

    async def _fetch_sub(
        self,
        client: httpx.AsyncClient,
        sub_cfg: dict,
        settings: dict,
    ) -> AsyncIterator[RawDiscovery]:
        sub = sub_cfg.get("name")
        if not sub:
            return
        mode = sub_cfg.get("mode", "hot")
        mode_time = sub_cfg.get("mode_time", "")
        url = f"{self.BASE_URL}/r/{sub}/{mode}.json?limit=25"
        if mode == "top" and mode_time:
            url += f"&t={mode_time}"

        try:
            res = await client.get(url)
            if res.status_code != 200:
                logger.warning(f"reddit r/{sub} status={res.status_code}")
                return
            data = res.json()
        except Exception as e:
            logger.warning(f"reddit r/{sub} failed: {e}")
            return

        posts = (data.get("data") or {}).get("children") or []
        min_upvotes = sub_cfg.get("min_upvotes", 50)
        max_age_seconds = float(settings.get("max_age_hours", 48)) * 3600
        skip_stickied = settings.get("skip_stickied", True)
        skip_nsfw = settings.get("skip_nsfw", True)
        now = time.time()

        for post in posts:
            p = post.get("data") or {}
            if p.get("score", 0) < min_upvotes:
                continue
            if skip_stickied and p.get("stickied"):
                continue
            if skip_nsfw and p.get("over_18"):
                continue
            created = float(p.get("created_utc") or 0)
            if created and (now - created) > max_age_seconds:
                continue

            title = p.get("title", "")
            selftext = (p.get("selftext") or "")[:400]
            url_external = p.get("url_overridden_by_dest") or p.get("url", "")
            permalink = f"https://www.reddit.com{p.get('permalink', '')}"

            yield RawDiscovery(
                source_type="reddit",
                source_name=f"r/{sub}",
                url=permalink,
                title=title,
                raw_text=selftext or f"[link post: {url_external}]",
                language="en",
                metadata={
                    "upvotes": p.get("score", 0),
                    "comments": p.get("num_comments", 0),
                    "external_url": url_external,
                    "author": p.get("author", ""),
                    "created_utc": created,
                },
            )
