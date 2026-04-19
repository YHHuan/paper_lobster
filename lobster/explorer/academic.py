"""Academic search APIs — arXiv + Semantic Scholar + PubMed.

All free, no API keys required. Provides access to actual research papers
instead of relying solely on Tavily web search.
"""

import logging
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger("lobster.explorer.academic")

ARXIV_API = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
PUBMED_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class AcademicSearch:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def search_arxiv(self, query: str, max_results: int = 5) -> list[dict]:
        """Search arXiv for recent papers.

        Returns list of {title, url, content, source} dicts.
        """
        try:
            resp = await self.client.get(
                ARXIV_API,
                params={
                    "search_query": f"all:{query}",
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
            resp.raise_for_status()
            return self._parse_arxiv_xml(resp.text)
        except Exception as e:
            logger.error(f"arXiv search failed: {e}")
            return []

    async def search_semantic_scholar(
        self, query: str, max_results: int = 5
    ) -> list[dict]:
        """Search Semantic Scholar for papers with citation counts.

        Free: 100 requests per 5 minutes (no key needed).
        """
        try:
            resp = await self.client.get(
                f"{SEMANTIC_SCHOLAR_API}/paper/search",
                params={
                    "query": query,
                    "limit": max_results,
                    "fields": "title,abstract,url,year,citationCount,authors,venue",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for paper in data.get("data", []):
                abstract = paper.get("abstract") or ""
                authors = ", ".join(
                    a.get("name", "") for a in (paper.get("authors") or [])[:3]
                )
                venue = paper.get("venue") or ""
                year = paper.get("year") or ""
                citations = paper.get("citationCount") or 0

                content = abstract
                if authors:
                    content = f"Authors: {authors}. "
                    if venue:
                        content += f"Published in {venue} ({year}). "
                    if citations:
                        content += f"Citations: {citations}. "
                    content += abstract

                results.append({
                    "title": paper.get("title", ""),
                    "url": paper.get("url", ""),
                    "content": content[:2000],
                    "source": "semantic_scholar",
                    "citations": citations,
                })
            return results

        except Exception as e:
            logger.error(f"Semantic Scholar search failed: {e}")
            return []

    async def search_pubmed(self, query: str, max_results: int = 5) -> list[dict]:
        """Search PubMed via E-utilities (completely free).

        Two-step: esearch (get IDs) → efetch (get details).
        """
        try:
            # Step 1: Search for IDs
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

            # Step 2: Fetch details
            fetch_resp = await self.client.get(
                f"{PUBMED_API}/efetch.fcgi",
                params={
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "retmode": "xml",
                },
            )
            fetch_resp.raise_for_status()
            return self._parse_pubmed_xml(fetch_resp.text)

        except Exception as e:
            logger.error(f"PubMed search failed: {e}")
            return []

    async def search_all(self, query: str, max_results: int = 3) -> list[dict]:
        """Search all academic sources. arXiv+PubMed in parallel, Semantic Scholar sequential."""
        import asyncio

        # arXiv and PubMed in parallel (no rate limits)
        results = await asyncio.gather(
            self.search_arxiv(query, max_results),
            self.search_pubmed(query, max_results),
            return_exceptions=True,
        )
        # Semantic Scholar has strict rate limits (100/5min), run separately
        try:
            ss = await self.search_semantic_scholar(query, max_results)
            results = list(results) + [ss]
        except Exception as e:
            results = list(results) + [e]

        combined = []
        for r in results:
            if isinstance(r, list):
                combined.extend(r)
        return combined

    def _parse_arxiv_xml(self, xml_text: str) -> list[dict]:
        """Parse arXiv Atom XML response."""
        results = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
                summary = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
                link = ""
                for link_el in entry.findall("atom:link", ns):
                    if link_el.get("type") == "text/html":
                        link = link_el.get("href", "")
                        break
                if not link:
                    id_text = entry.findtext("atom:id", "", ns)
                    link = id_text

                authors = []
                for author in entry.findall("atom:author", ns):
                    name = author.findtext("atom:name", "", ns)
                    if name:
                        authors.append(name)

                content = f"Authors: {', '.join(authors[:3])}. {summary}"
                results.append({
                    "title": title,
                    "url": link,
                    "content": content[:2000],
                    "source": "arxiv",
                })
        except ET.ParseError as e:
            logger.error(f"arXiv XML parse error: {e}")
        return results

    def _parse_pubmed_xml(self, xml_text: str) -> list[dict]:
        """Parse PubMed efetch XML response."""
        results = []
        try:
            root = ET.fromstring(xml_text)
            for article in root.findall(".//PubmedArticle"):
                medline = article.find("MedlineCitation")
                if medline is None:
                    continue

                art = medline.find("Article")
                if art is None:
                    continue

                title = art.findtext("ArticleTitle", "").strip()
                abstract_el = art.find("Abstract")
                abstract = ""
                if abstract_el is not None:
                    parts = []
                    for at in abstract_el.findall("AbstractText"):
                        label = at.get("Label", "")
                        text = at.text or ""
                        if label:
                            parts.append(f"{label}: {text}")
                        else:
                            parts.append(text)
                    abstract = " ".join(parts)

                pmid = medline.findtext("PMID", "")
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

                results.append({
                    "title": title,
                    "url": url,
                    "content": abstract[:2000],
                    "source": "pubmed",
                })
        except ET.ParseError as e:
            logger.error(f"PubMed XML parse error: {e}")
        return results

    async def close(self):
        await self.client.aclose()
