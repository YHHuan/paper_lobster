"""Headless browser for JS-heavy pages and screenshots.

Uses Playwright if available, falls back to Jina Reader.
Playwright requires: pip install playwright && playwright install chromium
"""

import logging

logger = logging.getLogger("lobster.explorer.browser")

try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logger.info("Playwright not installed — browser features disabled, using Jina fallback")


class HeadlessBrowser:
    def __init__(self):
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        if not HAS_PLAYWRIGHT:
            return False
        if self._browser is None:
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
            except Exception as e:
                logger.error(f"Failed to launch browser: {e}")
                return False
        return True

    @property
    def available(self) -> bool:
        return HAS_PLAYWRIGHT

    async def read_page(self, url: str, max_chars: int = 8000) -> str:
        """Render page with JS and extract text content."""
        if not await self._ensure_browser():
            return ""

        try:
            page = await self._browser.new_page()
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            # Wait a bit for JS to render
            await page.wait_for_timeout(2000)
            text = await page.inner_text("body")
            await page.close()
            return text[:max_chars]
        except Exception as e:
            logger.error(f"Browser read failed for {url[:60]}: {e}")
            return ""

    async def screenshot(self, url: str, path: str = "/tmp/screenshot.png") -> str:
        """Take a screenshot of a page. Returns file path or empty string."""
        if not await self._ensure_browser():
            return ""

        try:
            page = await self._browser.new_page(viewport={"width": 1280, "height": 800})
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await page.screenshot(path=path, full_page=False)
            await page.close()
            logger.info(f"Screenshot saved: {path}")
            return path
        except Exception as e:
            logger.error(f"Screenshot failed for {url[:60]}: {e}")
            return ""

    async def extract_links(self, url: str) -> list[dict]:
        """Extract all links from a page. Returns [{text, href}]."""
        if not await self._ensure_browser():
            return []

        try:
            page = await self._browser.new_page()
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            links = await page.eval_on_selector_all(
                "a[href]",
                """els => els.map(a => ({
                    text: a.innerText.trim().substring(0, 100),
                    href: a.href
                })).filter(l => l.text && l.href.startsWith('http'))"""
            )
            await page.close()
            return links[:50]
        except Exception as e:
            logger.error(f"Link extraction failed for {url[:60]}: {e}")
            return []

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
