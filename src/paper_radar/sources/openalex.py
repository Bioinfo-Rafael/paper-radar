from __future__ import annotations

import logging
from datetime import date
from typing import Any

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text, parse_date

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.openalex.org/works"
SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_date",
        "primary_location",
        "cited_by_count",
        "ids",
        "abstract_inverted_index",
        "authorships",
    ]
)


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, indices in inverted_index.items():
        for index in indices:
            positions[index] = word
    if not positions:
        return ""
    return clean_text(" ".join(positions[i] for i in sorted(positions)))


class OpenAlexSource:
    """Supplemental, key-free candidate discovery across every category.

    Missing or broken never blocks the pipeline: every call is wrapped and
    a failure simply contributes no candidates for that query.
    """

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def search(self, queries: list[str], start: date, end: date, limit: int) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        for query in queries:
            try:
                payload = self.client.get_json(
                    BASE_URL,
                    params={
                        "search": query,
                        "filter": (
                            f"from_publication_date:{start.isoformat()},"
                            f"to_publication_date:{end.isoformat()}"
                        ),
                        "per-page": min(limit, 200),
                        "mailto": "paper-radar@example.invalid",
                        "select": SELECT_FIELDS,
                    },
                    health_key="openalex",
                )
            except Exception:
                LOGGER.exception("OpenAlex query failed", extra={"query": query})
                continue
            for item in payload.get("results", []):
                papers.extend(self._to_paper(item, seen))
        return papers[:limit]

    def _to_paper(self, item: dict[str, Any], seen: set[str]) -> list[Paper]:
        title = clean_text(item.get("title") or item.get("display_name"))
        openalex_id = (item.get("id") or "").rsplit("/", 1)[-1] or None
        if not title or not openalex_id or openalex_id in seen:
            return []
        seen.add(openalex_id)
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        venue = clean_text(source.get("display_name") or "")
        authors = [
            clean_text((authorship.get("author") or {}).get("display_name", ""))
            for authorship in item.get("authorships") or []
        ]
        doi = item.get("doi")
        ids = item.get("ids") or {}
        pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1] or None
        return [
            Paper(
                title=title,
                abstract=_reconstruct_abstract(item.get("abstract_inverted_index")),
                publication_date=parse_date(item.get("publication_date")),
                venue=venue or None,
                doi=doi,
                pubmed_id=pmid,
                openalex_id=openalex_id,
                authors=[name for name in authors if name],
                citation_count=item.get("cited_by_count"),
                paper_url=primary.get("landing_page_url") or item.get("id") or "",
                source="openalex",
            )
        ]
