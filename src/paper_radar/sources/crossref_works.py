from __future__ import annotations

import logging
from datetime import date

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import (
    clean_text,
    crossref_abstract,
    crossref_authors,
    crossref_date_parts,
)

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.crossref.org/works"


class CrossrefWorksSource:
    """General Crossref works search, scoped to specific venue names.

    Distinct from CrossrefPreprintSource (which is scoped to the bioRxiv/
    openRxiv DOI prefixes) -- this queries Crossref's general works index
    directly by container-title, mainly for Archive-lane top/strong-venue
    recall of journal- and conference-published DOIs.
    """

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, venues: list[str], start: date, end: date, limit_per_venue: int) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        for venue in venues:
            try:
                payload = self.client.get_json(
                    BASE_URL,
                    params={
                        "query.container-title": venue,
                        "filter": ",".join(
                            (
                                f"from-pub-date:{start.isoformat()}",
                                f"until-pub-date:{end.isoformat()}",
                            )
                        ),
                        "rows": min(limit_per_venue, 100),
                        "sort": "relevance",
                        "order": "desc",
                        "mailto": "paper-radar@example.invalid",
                    },
                    health_key="crossref.works",
                )
            except Exception:
                LOGGER.exception("Crossref works query failed", extra={"venue": venue})
                continue
            for item in payload.get("message", {}).get("items", []):
                doi = item.get("DOI")
                title_values = item.get("title") or []
                published = crossref_date_parts(item)
                if (
                    not doi
                    or doi.casefold() in seen
                    or not title_values
                    or (published and not start <= published <= end)
                ):
                    continue
                seen.add(doi.casefold())
                container = (item.get("container-title") or [venue])[0]
                papers.append(
                    Paper(
                        title=clean_text(title_values[0]),
                        abstract=crossref_abstract(item.get("abstract")),
                        publication_date=published,
                        venue=clean_text(container) or venue,
                        publication_type=item.get("type"),
                        doi=doi,
                        authors=crossref_authors(item),
                        citation_count=item.get("is-referenced-by-count"),
                        paper_url=item.get("URL") or f"https://doi.org/{doi}",
                        source="crossref_works",
                    )
                )
        return papers[: limit_per_venue * max(1, len(venues))]
