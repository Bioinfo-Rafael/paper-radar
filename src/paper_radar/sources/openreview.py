from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text

LOGGER = logging.getLogger(__name__)
SEARCH_URL = "https://api2.openreview.net/notes/search"
EXCLUDED_STATUS_TERMS = ("withdraw", "reject", "desk reject")


def _value(field: Any) -> Any:
    if isinstance(field, dict):
        return field.get("value")
    return field


class OpenReviewSource:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def search(
        self,
        queries: list[str],
        start: date,
        end: date,
        limit: int,
        venues: tuple[str, ...] = (),
    ) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        for query in queries:
            try:
                payload = self.client.get_json(
                    SEARCH_URL,
                    params={
                        "query": query,
                        "content": "all",
                        "group": "all",
                        "source": "all",
                        "limit": min(limit, 1000),
                    },
                    health_key="openreview",
                )
            except Exception:
                LOGGER.exception("OpenReview query failed", extra={"query": query})
                continue
            for note in payload.get("notes", []):
                paper = self._to_paper(note, start, end, venues, seen)
                if paper:
                    papers.append(paper)
        return papers[:limit]

    def _to_paper(
        self,
        note: dict[str, Any],
        start: date,
        end: date,
        venues: tuple[str, ...],
        seen: set[str],
    ) -> Paper | None:
        note_id = note.get("id")
        if not note_id or note_id in seen:
            return None
        content = note.get("content") or {}
        title = clean_text(_value(content.get("title")))
        if not title:
            return None
        venue_text = clean_text(_value(content.get("venue")) or "")
        lowered = venue_text.casefold()
        if any(term in lowered for term in EXCLUDED_STATUS_TERMS):
            return None
        if venues and not any(candidate.casefold() in lowered for candidate in venues):
            return None
        created_ms = note.get("pdate") or note.get("cdate")
        pub_date = (
            datetime.fromtimestamp(created_ms / 1000, tz=UTC).date() if created_ms else None
        )
        if pub_date and not start <= pub_date <= end:
            return None
        raw_authors = _value(content.get("authors"))
        authors = [clean_text(a) for a in raw_authors] if isinstance(raw_authors, list) else []
        seen.add(note_id)
        return Paper(
            title=title,
            abstract=clean_text(_value(content.get("abstract"))),
            publication_date=pub_date,
            venue=venue_text or "OpenReview",
            publication_type="Conference Paper",
            authors=[name for name in authors if name],
            paper_url=f"https://openreview.net/forum?id={note_id}",
            source="openreview",
        )
