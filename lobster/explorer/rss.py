"""RSS feed reader.

Fetches and parses RSS/Atom feeds from the rss_sources table.
"""

import logging
from datetime import datetime, timezone

import feedparser

logger = logging.getLogger("lobster.explorer.rss")


class RSSReader:
    def __init__(self, db):
        self.db = db

    async def fetch_all_sources(self) -> list[dict]:
        """Fetch new items from all active RSS sources.

        Returns:
            List of {title, url, summary, source_name, published_at} dicts.
        """
        sources = await self.db.get_active_rss_sources()
        all_items = []

        for source in sources:
            try:
                items = await self._fetch_feed(source)
                all_items.extend(items)
                await self.db.update_rss_last_fetched(str(source["id"]))
            except Exception as e:
                logger.error(f"RSS fetch failed for {source.get('name')}: {e}")

        logger.info(f"RSS: fetched {len(all_items)} items from {len(sources)} sources")
        return all_items

    async def _fetch_feed(self, source: dict) -> list[dict]:
        """Parse a single RSS feed."""
        import asyncio

        url = source["url"]
        name = source.get("name", url)
        last_fetched = source.get("last_fetched_at")

        def _parse():
            return feedparser.parse(url)

        feed = await asyncio.get_event_loop().run_in_executor(None, _parse)

        items = []
        for entry in feed.entries[:10]:  # max 10 per source per fetch
            published = entry.get("published_parsed")
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if last_fetched:
                    try:
                        last_dt = datetime.fromisoformat(last_fetched.replace("Z", "+00:00"))
                        if pub_dt <= last_dt:
                            continue
                    except (ValueError, TypeError):
                        pass

            items.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "summary": entry.get("summary", "")[:500],
                "source_name": name,
                "content_type": source.get("category", "article"),
            })

        return items
