from __future__ import annotations

import logging
from datetime import date

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text, parse_date

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class EuropePMCSource:
    """Query-based recall for bioinfo; no API key required."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, queries: list[str], start: date, end: date, limit: int) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        for query in queries:
            full_query = f"({query}) AND FIRST_PDATE:[{start.isoformat()} TO {end.isoformat()}]"
            try:
                payload = self.client.get_json(
                    BASE_URL,
                    params={
                        "query": full_query,
                        "format": "json",
                        "resultType": "core",
                        "pageSize": min(limit, 1000),
                    },
                    health_key="europepmc",
                )
            except Exception:
                LOGGER.exception("Europe PMC query failed", extra={"query": query})
                continue
            for item in payload.get("resultList", {}).get("result", []):
                title = clean_text(item.get("title"))
                doi = item.get("doi")
                pmid = item.get("pmid")
                pmcid = item.get("pmcid")
                identity = doi or pmid or pmcid or title
                if not title or not identity or identity.casefold() in seen:
                    continue
                seen.add(identity.casefold())
                authors = [
                    name.strip()
                    for name in (item.get("authorString") or "").split(",")
                    if name.strip()
                ]
                pub_date = parse_date(
                    item.get("firstPublicationDate") or str(item.get("pubYear") or "")
                )
                venue = clean_text(
                    item.get("journalTitle")
                    or (item.get("bookOrReportDetails") or {}).get("publisher")
                    or ""
                )
                papers.append(
                    Paper(
                        title=title,
                        abstract=clean_text(item.get("abstractText")),
                        publication_date=pub_date,
                        venue=venue or None,
                        publication_type=item.get("pubType"),
                        doi=doi,
                        biorxiv_doi=doi
                        if doi and str(doi).lower().startswith(("10.1101/", "10.64898/"))
                        else None,
                        pubmed_id=pmid,
                        authors=authors,
                        citation_count=item.get("citedByCount"),
                        paper_url=f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}",
                        source="europepmc",
                    )
                )
        return papers[:limit]
