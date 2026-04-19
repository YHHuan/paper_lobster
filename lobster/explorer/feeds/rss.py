"""RSS + Google News feed explorers.

Both wrap feedparser, but Google News builds the URL from a search query so it
acts as a generic crawler shim for any site that doesn't expose an RSS feed.
"""

import asyncio
import logging
from typing import AsyncIterator
from urllib.parse import quote

import feedparser
import httpx

from .base import BaseFeedExplorer, RawDiscovery

logger = logging.getLogger("lobster.explorer.feeds.rss")

USER_AGENT = "Lobster/4.0 (+https://github.com/lobster)"


def _parse_feed(content: bytes):
    return feedparser.parse(content)


class RSSExplorer(BaseFeedExplorer):
    name = "rss"

    async def fetch(self, config: dict) -> AsyncIterator[RawDiscovery]:
        sources = config.get("sources") or []
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
            for source in sources:
                async for item in self._fetch_one(client, source):
                    yield item

    async def _fetch_one(self, client: httpx.AsyncClient, source: dict) -> AsyncIterator[RawDiscovery]:
        url = source.get("url")
        if not url:
            return
        name = source.get("name", url)
        language = source.get("language", "en")
        max_items = source.get("max_items", 20)
        try:
            res = await client.get(url)
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"rss fetch failed name={name} url={url}: {e}")
            return

        parsed = await asyncio.get_event_loop().run_in_executor(None, _parse_feed, res.content)
        for entry in (parsed.entries or [])[:max_items]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            summary = (entry.get("summary") or entry.get("description") or "")[:500]
            if not link or not title:
                continue
            yield RawDiscovery(
                source_type="rss",
                source_name=name,
                url=link,
                title=title,
                raw_text=summary,
                language=language,
                metadata={
                    "published": entry.get("published", ""),
                    "author": entry.get("author", ""),
                },
            )


class GoogleNewsExplorer(BaseFeedExplorer):
    """Use Google News search RSS as a universal crawler shim."""

    name = "google_news"
    BASE_URL = "https://news.google.com/rss/search"

    async def fetch(self, config: dict) -> AsyncIterator[RawDiscovery]:
        sources = config.get("google_news_sources") or []
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
            for source in sources:
                async for item in self._fetch_one(client, source):
                    yield item
                # Be polite to Google News.
                await asyncio.sleep(1)

    async def _fetch_one(self, client: httpx.AsyncClient, source: dict) -> AsyncIterator[RawDiscovery]:
        query = source.get("query")
        if not query:
            return
        name = source.get("name", query)
        language = source.get("language", "en")
        max_items = source.get("max_items", 15)

        hl = "zh-TW" if language == "zh" else "en-US"
        gl = "TW" if language == "zh" else "US"
        url = f"{self.BASE_URL}?q={quote(query)}&hl={hl}&gl={gl}&ceid={gl}:{hl.split('-')[0]}"

        try:
            res = await client.get(url)
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"google_news fetch failed name={name}: {e}")
            return

        parsed = await asyncio.get_event_loop().run_in_executor(None, _parse_feed, res.content)
        for entry in (parsed.entries or [])[:max_items]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            if not link or not title:
                continue
            origin = ""
            src_obj = getattr(entry, "source", None)
            if isinstance(src_obj, dict):
                origin = src_obj.get("title", "")
            elif src_obj is not None:
                origin = getattr(src_obj, "title", "") or ""
            yield RawDiscovery(
                source_type="google_news",
                source_name=name,
                url=link,
                title=title,
                raw_text=(entry.get("summary") or "")[:500],
                language=language,
                metadata={
                    "published": entry.get("published", ""),
                    "original_source": origin,
                },
            )
