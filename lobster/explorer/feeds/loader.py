"""YAML config loader for feed explorers.

Loads source/feeds/*.yml and filters by tier so the coordinator can decide
which sources participate in a given run (morning = core only, evening =
core + extended, weekend optionally adds experimental).
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger("lobster.explorer.feeds.loader")

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "feeds"

# Map yaml file → explorer key recognised by coordinator.
FILE_TO_EXPLORER = {
    "rss_feeds.yml":   "rss",
    "google_news.yml": "google_news",
    "reddit_subs.yml": "reddit",
    "hackernews.yml":  "hackernews",
}


class SourceLoader:
    def __init__(self, config_dir: Path | str | None = None):
        self.config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR

    def _load(self, filename: str) -> dict:
        path = self.config_dir / filename
        if not path.exists():
            logger.debug(f"config not found: {path}")
            return {}
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            logger.error(f"yaml parse error in {path}: {e}")
            return {}

    def load_topics(self) -> dict:
        return self._load("topics.yml").get("current_topics", {})

    def load_noise_filters(self) -> dict:
        return self._load("noise_filters.yml").get("noise_filters", {})

    def load_filtered(self, active_tiers: list[str]) -> dict[str, dict]:
        """Return {explorer_name: filtered_config} keyed by FILE_TO_EXPLORER mapping.

        Each list-based config is filtered so only entries whose `tier` is in
        active_tiers (or has no tier set, treated as 'core') are kept.
        """
        active = set(active_tiers)
        out: dict[str, dict] = {}

        for filename, explorer in FILE_TO_EXPLORER.items():
            data = self._load(filename)
            if not data:
                continue

            if explorer == "rss":
                items = data.get("rss_sources", [])
                kept = [s for s in items if s.get("tier", "core") in active]
                if kept:
                    out["rss"] = {"sources": kept}
            elif explorer == "google_news":
                items = data.get("google_news_sources", [])
                kept = [s for s in items if s.get("tier", "core") in active]
                if kept:
                    out["google_news"] = {"google_news_sources": kept}
            elif explorer == "reddit":
                subs = data.get("subreddits", [])
                kept = [s for s in subs if s.get("tier", "core") in active]
                if kept:
                    out["reddit"] = {
                        "subreddits": kept,
                        "fetch_settings": data.get("fetch_settings", {}),
                    }
            elif explorer == "hackernews":
                # HN is not tiered; include if enabled and 'core' is active.
                hn = data.get("hackernews", {})
                if hn.get("enabled") and "core" in active:
                    out["hackernews"] = {"hackernews": hn}

        return out

    def merge_dynamic_sources(self, base: dict[str, dict], dynamic_rows: list[dict]) -> dict[str, dict]:
        """Append rows from `dynamic_sources` table (status='active') to base configs.

        Rows have shape: {source_type, source_config (jsonb), status, ...}.
        Treat each as a single-entry source belonging to its explorer.
        """
        for row in dynamic_rows or []:
            stype = row.get("source_type")
            cfg = row.get("source_config") or {}
            if stype == "rss":
                base.setdefault("rss", {"sources": []})["sources"].append(cfg)
            elif stype == "google_news":
                base.setdefault("google_news", {"google_news_sources": []})[
                    "google_news_sources"
                ].append(cfg)
            elif stype == "reddit":
                base.setdefault("reddit", {"subreddits": [], "fetch_settings": {}})[
                    "subreddits"
                ].append(cfg)
        return base
