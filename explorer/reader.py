"""Jina Reader API client.

Reads web pages and returns clean text. Free, no API key needed.
"""

import logging

import httpx

logger = logging.getLogger("lobster.explorer.reader")

JINA_READER_URL = "https://r.jina.ai"


class JinaReader:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "text/plain"},
        )

    async def read(self, url: str, max_chars: int = 5000) -> str:
        """Read a web page and return clean text.

        Args:
            url: URL to read.
            max_chars: Max characters to return.

        Returns:
            Clean text content, or empty string on failure.
        """
        try:
            resp = await self.client.get(f"{JINA_READER_URL}/{url}")
            resp.raise_for_status()
            text = resp.text[:max_chars]
            logger.info(f"Jina read {url[:60]} → {len(text)} chars")
            return text
        except Exception as e:
            logger.error(f"Jina read failed for {url[:60]}: {e}")
            return ""

    async def close(self):
        await self.client.aclose()
