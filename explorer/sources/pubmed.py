"""PubMed E-utilities source adapter."""

import logging
import xml.etree.ElementTree as ET

import httpx

from .base import OpenQuestion, RawFind, Source

logger = logging.getLogger("lobster.sources.pubmed")

PUBMED_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedSource(Source):
    name = "pubmed"

    def __init__(self, llm=None):
        self.llm = llm  # for question_to_query refinement
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(self, question: OpenQuestion, max_results: int = 5) -> list[RawFind]:
        query = question.question
        try:
            search_resp = await self.client.get(
                f"{PUBMED_API}/esearch.fcgi",
                params={
                    "db": "pubmed",
                    "term": query,
                    "retmax": max_results,
                    "sort": "date",
                    "retmode": "json",
                },
            )
            search_resp.raise_for_status()
            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []

            fetch_resp = await self.client.get(
                f"{PUBMED_API}/efetch.fcgi",
                params={
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "retmode": "xml",
                },
            )
            fetch_resp.raise_for_status()
            return self._parse(fetch_resp.text)
        except Exception as e:
            logger.error(f"pubmed search failed: {e}")
            return []

    def _parse(self, xml_text: str) -> list[RawFind]:
        out = []
        try:
            root = ET.fromstring(xml_text)
            for article in root.findall(".//PubmedArticle"):
                medline = article.find("MedlineCitation")
                if medline is None:
                    continue
                art = medline.find("Article")
                if art is None:
                    continue
                title = (art.findtext("ArticleTitle", "") or "").strip()

                # Abstract
                abstract = ""
                ab = art.find("Abstract")
                if ab is not None:
                    parts = []
                    for at in ab.findall("AbstractText"):
                        label = at.get("Label", "")
                        text = at.text or ""
                        parts.append(f"{label}: {text}" if label else text)
                    abstract = " ".join(parts)

                # Journal
                journal = ""
                jrnl = art.find("Journal")
                if jrnl is not None:
                    journal = (jrnl.findtext("Title", "") or "").strip()

                # Pub date
                pub_date = ""
                pd = art.find(".//PubDate")
                if pd is not None:
                    year = pd.findtext("Year", "")
                    month = pd.findtext("Month", "")
                    pub_date = f"{year} {month}".strip()

                pmid = (medline.findtext("PMID", "") or "").strip()
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None

                out.append(
                    RawFind(
                        source_type="pubmed",
                        title=title,
                        url=url,
                        content=abstract,
                        source_id=pmid,
                        metadata={
                            "journal": journal,
                            "pub_date": pub_date,
                            "abstract": abstract,
                        },
                    )
                )
        except ET.ParseError as e:
            logger.error(f"pubmed xml parse error: {e}")
        return out

    async def close(self):
        await self.client.aclose()
