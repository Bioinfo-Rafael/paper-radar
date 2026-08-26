from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text, parse_date

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.biorxiv.org"


class BiorxivSource:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def _page(
        self,
        endpoint: str,
        start: date,
        end: date,
        page_size: int,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        base = f"{BASE_URL}/{endpoint}/biorxiv/{start.isoformat()}/{end.isoformat()}"
        params = {"category": category.replace(" ", "_")} if category else None

        def fetch(cursor: int) -> dict[str, Any]:
            return self.client.get_json(f"{base}/{cursor}", params=params)

        first = fetch(0)
        records = list(first.get("collection", []))
        messages = first.get("messages") or []
        total = int(messages[0].get("total", len(records))) if messages else len(records)
        cursors = list(range(page_size, total, page_size))
        # bioRxiv pages are independent; a small pool keeps the 14-day overlap practical.
        with ThreadPoolExecutor(max_workers=2) as executor:
            for payload in executor.map(fetch, cursors):
                records.extend(payload.get("collection", []))
        return records

    def fetch(self, start: date, end: date, categories: list[str]) -> list[Paper]:
        wanted = {value.casefold() for value in categories}
        papers: list[Paper] = []
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                category_pages = executor.map(
                    lambda category: self._page("details", start, end, 30, category),
                    categories,
                )
                details = [item for page in category_pages for item in page]
            latest: dict[str, dict[str, Any]] = {}
            for item in details:
                category = str(item.get("category", "")).casefold()
                if category not in wanted:
                    continue
                doi = item.get("doi")
                if doi:
                    latest[doi] = item  # API order means later versions replace earlier ones.
            for item in latest.values():
                doi = item.get("doi")
                papers.append(
                    Paper(
                        title=clean_text(item.get("title")) or "Untitled paper",
                        abstract=clean_text(item.get("abstract")),
                        publication_date=parse_date(item.get("date")),
                        venue="bioRxiv",
                        publication_type="Preprint",
                        doi=None,
                        biorxiv_doi=doi,
                        preprint_doi=doi,
                        paper_url=f"https://doi.org/{doi}",
                        source="biorxiv",
                        categories=[item.get("category")] if item.get("category") else [],
                    )
                )
        except Exception:
            LOGGER.exception("bioRxiv content fetch failed")

        # Formal-publication events are intentionally distinct from their preprint identity.
        try:
            for item in self._page("pubs", start, end, 100):
                preprint_doi = item.get("biorxiv_doi")
                published_doi = item.get("published_doi")
                category = str(item.get("preprint_category", "")).casefold()
                if not published_doi or (category and category not in wanted):
                    continue
                papers.append(
                    Paper(
                        title=clean_text(item.get("preprint_title")) or "Untitled paper",
                        abstract=clean_text(item.get("preprint_abstract")),
                        publication_date=parse_date(item.get("published_date")),
                        venue=clean_text(item.get("published_journal")) or "Published article",
                        publication_type="Journal Article",
                        doi=published_doi,
                        biorxiv_doi=preprint_doi,
                        preprint_doi=preprint_doi,
                        published_doi=published_doi,
                        paper_url=f"https://doi.org/{published_doi}",
                        source="biorxiv_publication",
                        categories=[item.get("preprint_category")]
                        if item.get("preprint_category")
                        else [],
                    )
                )
        except Exception:
            LOGGER.exception("bioRxiv publication mapping fetch failed")
        return papers
