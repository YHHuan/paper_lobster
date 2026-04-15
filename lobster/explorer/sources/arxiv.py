"""arXiv API source adapter."""

import logging
import xml.etree.ElementTree as ET

import httpx

from .base import OpenQuestion, RawFind, Source

logger = logging.getLogger("lobster.sources.arxiv")

ARXIV_API = "https://export.arxiv.org/api/query"


class ArXivSource(Source):
    name = "arxiv"

    def __init__(self, llm=None):
        self.llm = llm
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def search(self, question: OpenQuestion, max_results: int = 5) -> list[RawFind]:
        try:
            resp = await self.client.get(
                ARXIV_API,
                params={
                    "search_query": f"all:{question.question}",
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
            resp.raise_for_status()
            return self._parse(resp.text)
        except Exception as e:
            logger.error(f"arxiv search failed: {e}")
            return []

    def _parse(self, xml_text: str) -> list[RawFind]:
        out = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
                summary = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")
                pub_date = (entry.findtext("atom:published", "", ns) or "").strip()

                link = ""
                for l in entry.findall("atom:link", ns):
                    if l.get("type") == "text/html":
                        link = l.get("href", "")
                        break
                if not link:
                    link = (entry.findtext("atom:id", "", ns) or "")

                arxiv_id = link.rstrip("/").split("/")[-1] if link else None

                authors = []
                for author in entry.findall("atom:author", ns):
                    name = author.findtext("atom:name", "", ns)
                    if name:
                        authors.append(name)
                authors_str = ", ".join(authors[:5])

                out.append(
                    RawFind(
                        source_type="arxiv",
                        title=title,
                        url=link,
                        content=summary,
                        source_id=arxiv_id,
                        metadata={
                            "authors": authors_str,
                            "pub_date": pub_date,
                            "abstract": summary,
                        },
                    )
                )
        except ET.ParseError as e:
            logger.error(f"arxiv xml parse error: {e}")
        return out

    async def close(self):
        await self.client.aclose()
