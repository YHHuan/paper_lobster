"""PDF text extraction for academic papers.

Uses pymupdf (fitz) if available, falls back to Jina Reader for PDF URLs.
Install: pip install pymupdf
"""

import logging
import tempfile

import httpx

logger = logging.getLogger("lobster.explorer.pdf")

try:
    import fitz  # pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    logger.info("pymupdf not installed — PDF extraction limited to Jina fallback")

JINA_READER_URL = "https://r.jina.ai"


class PDFReader:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    async def extract_from_url(self, url: str, max_chars: int = 10000) -> str:
        """Download PDF and extract text.

        Strategy:
        1. If pymupdf available: download → local parse (best quality)
        2. Fallback: Jina Reader (handles some PDFs)
        """
        if HAS_PYMUPDF:
            return await self._extract_with_pymupdf(url, max_chars)
        return await self._extract_with_jina(url, max_chars)

    async def extract_from_bytes(self, pdf_bytes: bytes, max_chars: int = 10000) -> str:
        """Extract text from PDF bytes (for locally stored PDFs)."""
        if not HAS_PYMUPDF:
            return ""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            return self._extract_text(doc, max_chars)
        except Exception as e:
            logger.error(f"PDF bytes extraction failed: {e}")
            return ""

    async def _extract_with_pymupdf(self, url: str, max_chars: int) -> str:
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            doc = fitz.open(stream=resp.content, filetype="pdf")
            text = self._extract_text(doc, max_chars)
            logger.info(f"PDF extracted ({len(doc)} pages, {len(text)} chars): {url[:60]}")
            return text
        except Exception as e:
            logger.error(f"pymupdf extraction failed for {url[:60]}: {e}")
            return await self._extract_with_jina(url, max_chars)

    def _extract_text(self, doc, max_chars: int) -> str:
        """Extract structured text from pymupdf document."""
        parts = []
        total = 0
        for page in doc:
            text = page.get_text("text")
            parts.append(text)
            total += len(text)
            if total >= max_chars:
                break
        full = "\n\n".join(parts)
        return full[:max_chars]

    async def _extract_with_jina(self, url: str, max_chars: int) -> str:
        try:
            resp = await self.client.get(
                f"{JINA_READER_URL}/{url}",
                headers={"Accept": "text/plain"},
            )
            resp.raise_for_status()
            text = resp.text[:max_chars]
            logger.info(f"PDF via Jina ({len(text)} chars): {url[:60]}")
            return text
        except Exception as e:
            logger.error(f"Jina PDF fallback failed for {url[:60]}: {e}")
            return ""

    @staticmethod
    def is_pdf_url(url: str) -> bool:
        """Check if URL likely points to a PDF."""
        url_lower = url.lower()
        if url_lower.endswith(".pdf"):
            return True
        # Common academic PDF patterns
        if "arxiv.org/pdf/" in url_lower:
            return True
        if "/pdf/" in url_lower and any(d in url_lower for d in ["ncbi", "pmc", "nature", "science"]):
            return True
        return False

    async def close(self):
        await self.client.aclose()
