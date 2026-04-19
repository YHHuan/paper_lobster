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
    """Reddit JSON explorer using old.reddit.com — www.reddit.com rate-limits bots hard."""

    name = "reddit"
    BASE_URL = "https://old.reddit.com"

    async def fetch(self, config: dict) -> AsyncIterator[RawDiscovery]:
        subreddits = config.get("subreddits") or []
        settings = config.get("fetch_settings") or {}
        pause = float(settings.get("request_pause_seconds", 3))

        # Use a fresh client per sub to avoid reddit's session-level rate limit
        # that kicks in aggressively once it decides a client is a bot.
        for sub_cfg in subreddits:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers=HEADERS,
                follow_redirects=True,
            ) as client:
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

        data = None
        for attempt in range(3):
            try:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    break
                if res.status_code in (403, 429):
                    backoff = 5 * (attempt + 1)
                    logger.info(f"reddit r/{sub} status={res.status_code}, backing off {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                logger.warning(f"reddit r/{sub} status={res.status_code}")
                return
            except Exception as e:
                logger.warning(f"reddit r/{sub} failed: {e}")
                return
        if data is None:
            logger.warning(f"reddit r/{sub} gave up after retries")
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
