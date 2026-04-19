"""Feed exploration coordinator.

Loads YAML configs filtered by tier, runs all explorers in parallel, deduplicates
against discoveries seen in the last 7 days, and writes the rest into the
`discoveries` table for the digester / digest pipeline.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from hashlib import md5

from .base import RawDiscovery
from .hackernews import HackerNewsExplorer
from .loader import SourceLoader
from .reddit import RedditExplorer
from .rss import GoogleNewsExplorer, RSSExplorer

logger = logging.getLogger("lobster.explorer.feeds.coordinator")

DEFAULT_EXPLORERS = {
    "rss":         RSSExplorer,
    "google_news": GoogleNewsExplorer,
    "reddit":      RedditExplorer,
    "hackernews":  HackerNewsExplorer,
}


class FeedCoordinator:
    MAX_DISCOVERIES_PER_RUN = 80

    def __init__(
        self,
        db,
        loader: SourceLoader | None = None,
        explorers: dict | None = None,
    ):
        self.db = db
        self.loader = loader or SourceLoader()
        # Instantiate once and reuse.
        explorer_classes = explorers or DEFAULT_EXPLORERS
        self.explorers = {name: cls() for name, cls in explorer_classes.items()}

    @staticmethod
    def _hash_url(url: str) -> str:
        return md5((url or "").encode("utf-8")).hexdigest()

    def _passes_noise(self, item: RawDiscovery, filters: dict) -> bool:
        title_low = (item.title or "").lower()
        url_low = (item.url or "").lower()
        for needle in filters.get("drop_title_contains", []) or []:
            if needle.lower() in title_low:
                return False
        for needle in filters.get("drop_url_contains", []) or []:
            if needle.lower() in url_low:
                return False
        return True

    def _decide_tiers(self, mode: str) -> list[str]:
        if mode == "morning":
            tiers = ["core"]
        else:
            tiers = ["core", "extended"]
        if datetime.now().weekday() in (5, 6):
            tiers.append("experimental")
        return tiers

    async def _gather_dynamic(self) -> list[dict]:
        if not self.db or not hasattr(self.db, "get_active_dynamic_sources"):
            return []
        try:
            return await self.db.get_active_dynamic_sources()
        except Exception as e:
            logger.debug(f"dynamic source fetch skipped: {e}")
            return []

    async def _drain(self, name: str, config: dict) -> list[RawDiscovery]:
        explorer = self.explorers.get(name)
        if not explorer:
            return []
        items: list[RawDiscovery] = []
        try:
            async for item in explorer.fetch(config):
                items.append(item)
        except Exception as e:
            logger.warning(f"explorer {name} crashed: {e}")
        return items

    async def run_exploration(self, mode: str = "morning") -> dict:
        """Run a single coordinated exploration pass.

        Returns: {"inserted": int, "considered": int, "batch_id": str}
        """
        tiers = self._decide_tiers(mode)
        sources = self.loader.load_filtered(tiers)
        sources = self.loader.merge_dynamic_sources(sources, await self._gather_dynamic())
        noise = self.loader.load_noise_filters()

        if not sources:
            logger.info(f"no sources active for tiers={tiers}")
            return {"inserted": 0, "considered": 0, "batch_id": None}

        tasks = [self._drain(name, cfg) for name, cfg in sources.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_urls: set[str] = set()
        if self.db and hasattr(self.db, "get_recent_discovery_url_hashes"):
            try:
                seen_urls = await self.db.get_recent_discovery_url_hashes(days=7)
            except Exception as e:
                logger.warning(f"could not fetch recent url hashes: {e}")

        candidates: list[RawDiscovery] = []
        considered = 0
        for batch in results:
            if isinstance(batch, Exception):
                continue
            for item in batch:
                considered += 1
                if not item.url or not item.title:
                    continue
                h = self._hash_url(item.url)
                if h in seen_urls:
                    continue
                if not self._passes_noise(item, noise):
                    continue
                seen_urls.add(h)
                candidates.append(item)

        candidates.sort(
            key=lambda d: (d.metadata.get("score", 0) or 0)
            + (d.metadata.get("upvotes", 0) or 0)
            + (d.metadata.get("comments", 0) or 0),
            reverse=True,
        )
        candidates = candidates[: self.MAX_DISCOVERIES_PER_RUN]

        batch_id = str(uuid.uuid4())
        inserted = 0
        if self.db:
            for item in candidates:
                try:
                    await self.db.insert_discovery_raw(item, batch_id=batch_id)
                    inserted += 1
                except Exception as e:
                    logger.debug(f"insert_discovery_raw failed for {item.url}: {e}")

        logger.info(
            f"feed exploration mode={mode} tiers={tiers} "
            f"considered={considered} inserted={inserted} batch={batch_id}"
        )
        return {"inserted": inserted, "considered": considered, "batch_id": batch_id}

    async def close(self):
        for ex in self.explorers.values():
            try:
                await ex.close()
            except Exception:
                pass
