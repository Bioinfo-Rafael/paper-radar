from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import date

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text, parse_date

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedSource:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def _common_params(self) -> dict[str, str]:
        params = {"tool": "paper-radar"}
        if os.getenv("NCBI_EMAIL"):
            params["email"] = os.environ["NCBI_EMAIL"]
        if os.getenv("NCBI_API_KEY"):
            params["api_key"] = os.environ["NCBI_API_KEY"]
        return params

    @staticmethod
    def _text(element: ET.Element | None) -> str:
        return clean_text("".join(element.itertext()) if element is not None else "")

    def fetch(self, queries: list[str], start: date, end: date, limit: int) -> list[Paper]:
        ids: set[str] = set()
        for query in queries:
            params = self._common_params() | {
                "db": "pubmed",
                "retmode": "json",
                "retmax": str(limit),
                "term": query,
                "datetype": "pdat",
                "mindate": start.strftime("%Y/%m/%d"),
                "maxdate": end.strftime("%Y/%m/%d"),
            }
            try:
                data = self.client.get_json(
                    f"{BASE_URL}/esearch.fcgi", params=params, health_key="pubmed.search"
                )
                ids.update(data.get("esearchresult", {}).get("idlist", []))
            except Exception:
                LOGGER.exception("PubMed query failed", extra={"query": query})
        if not ids:
            return []
        papers: list[Paper] = []
        id_list = sorted(ids)
        for offset in range(0, len(id_list), 100):
            params = self._common_params() | {
                "db": "pubmed",
                "retmode": "xml",
                "id": ",".join(id_list[offset : offset + 100]),
            }
            try:
                response = self.client.request(
                    "GET", f"{BASE_URL}/efetch.fcgi", params=params, health_key="pubmed.fetch"
                )
                root = ET.fromstring(response.content)
            except Exception:
                LOGGER.exception("PubMed metadata fetch failed")
                continue
            for article in root.findall(".//PubmedArticle"):
                citation = article.find("MedlineCitation")
                journal_article = citation.find("Article") if citation is not None else None
                if citation is None or journal_article is None:
                    continue
                pmid = self._text(citation.find("PMID"))
                title = self._text(journal_article.find("ArticleTitle")) or "Untitled paper"
                abstract = " ".join(
                    self._text(x) for x in journal_article.findall("Abstract/AbstractText")
                )
                journal = self._text(journal_article.find("Journal/Title"))
                types = [
                    self._text(x)
                    for x in journal_article.findall("PublicationTypeList/PublicationType")
                ]
                article_ids = {
                    item.attrib.get("IdType", ""): self._text(item)
                    for item in article.findall("PubmedData/ArticleIdList/ArticleId")
                }
                pub_date_node = journal_article.find("Journal/JournalIssue/PubDate")
                year = self._text(pub_date_node.find("Year")) if pub_date_node is not None else ""
                medline_date = (
                    self._text(pub_date_node.find("MedlineDate"))
                    if pub_date_node is not None
                    else ""
                )
                month = self._text(pub_date_node.find("Month")) if pub_date_node is not None else ""
                day = self._text(pub_date_node.find("Day")) if pub_date_node is not None else ""
                pub_date = parse_date("-".join(x for x in (year, month, day) if x)) or parse_date(
                    medline_date
                )
                doi = article_ids.get("doi")
                authors = [
                    " ".join(
                        filter(
                            None,
                            (
                                self._text(author.find("ForeName")),
                                self._text(author.find("LastName")),
                            ),
                        )
                    )
                    for author in journal_article.findall("AuthorList/Author")
                ]
                papers.append(
                    Paper(
                        title=title,
                        abstract=abstract,
                        publication_date=pub_date,
                        venue=journal,
                        publication_type=", ".join(types),
                        doi=doi,
                        biorxiv_doi=doi if doi and doi.lower().startswith("10.1101/") else None,
                        pubmed_id=pmid or None,
                        authors=[name for name in authors if name],
                        paper_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        source="pubmed",
                        categories=[
                            self._text(x)
                            for x in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")
                        ],
                    )
                )
        return papers
