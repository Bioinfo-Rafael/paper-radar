from __future__ import annotations

import html
import logging
import math
import re
from datetime import date
from typing import Any

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.crossref.org/prefixes/{prefix}/works"


def _date_parts(item: dict[str, Any]) -> date | None:
    parts = (item.get("published") or item.get("created") or {}).get("date-parts", [[]])[0]
    if not parts:
        return None
    values = [int(value) for value in parts[:3]]
    while len(values) < 3:
        values.append(1)
    try:
        return date(*values)
    except ValueError:
        return None


def _abstract(value: str | None) -> str:
    if not value:
        return ""
    return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", value)))


class CrossrefPreprintSource:
    """Recall-oriented openRxiv metadata fallback, including the new 10.64898 prefix."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        start: date,
        end: date,
        limit: int,
        prefixes: tuple[str, ...] = ("10.64898", "10.1101"),
        queries: tuple[str, ...] = (),
    ) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        search_queries = queries or ("single cell computational method",)
        rows = min(50, max(10, math.ceil(limit / (len(prefixes) * len(search_queries)))))
        for prefix in prefixes:
            for query in search_queries:
                try:
                    payload = self.client.get_json(
                        BASE_URL.format(prefix=prefix),
                        params={
                            "filter": ",".join(
                                (
                                    f"from-pub-date:{start.isoformat()}",
                                    f"until-pub-date:{end.isoformat()}",
                                    "type:posted-content",
                                )
                            ),
                            "query.bibliographic": query,
                            "rows": rows,
                            "sort": "relevance",
                            "order": "desc",
                            "mailto": "paper-radar@example.invalid",
                        },
                    )
                except Exception:
                    LOGGER.exception(
                        "Crossref preprint fetch failed", extra={"prefix": prefix}
                    )
                    continue
                for item in payload.get("message", {}).get("items", []):
                    doi = item.get("DOI")
                    title_values = item.get("title") or []
                    published = _date_parts(item)
                    identity = str(doi).casefold()
                    if (
                        not doi
                        or identity in seen
                        or not title_values
                        or (published and not start <= published <= end)
                    ):
                        continue
                    seen.add(identity)
                    papers.append(
                        Paper(
                            title=clean_text(title_values[0]),
                            abstract=_abstract(item.get("abstract")),
                            publication_date=published,
                            venue="bioRxiv",
                            publication_type="Preprint",
                            biorxiv_doi=doi,
                            preprint_doi=doi,
                            paper_url=item.get("URL") or f"https://doi.org/{doi}",
                            source="crossref_preprint",
                        )
                    )
        return papers[:limit]
