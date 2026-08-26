from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text, parse_date

LOGGER = logging.getLogger(__name__)
GRAPH_URL = "https://api.semanticscholar.org/graph/v1"
RECOMMEND_URL = "https://api.semanticscholar.org/recommendations/v1"
FIELDS = ",".join(
    [
        "title",
        "abstract",
        "year",
        "venue",
        "publicationTypes",
        "publicationDate",
        "externalIds",
        "url",
        "fieldsOfStudy",
        "citationCount",
        "influentialCitationCount",
        "journal",
    ]
)


class SemanticScholarSource:
    def __init__(self, client: HttpClient) -> None:
        self.client = client
        api_key = os.getenv("S2_API_KEY")
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.public_rate_delay = 0.0 if api_key else 1.05
        self._last_request_at = 0.0
        self._rate_limited = False

    def _throttle(self) -> None:
        remaining = self.public_rate_delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _trip_rate_limit(self, exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if response is not None and response.status_code == 429:
            self._rate_limited = True
            LOGGER.warning(
                "Semantic Scholar rate-limit circuit opened; continuing with other sources. "
                "Set S2_API_KEY for reliable enrichment."
            )
            return True
        return False

    def _paper(self, item: dict[str, Any], source: str = "semantic_scholar") -> Paper:
        external = item.get("externalIds") or {}
        doi = external.get("DOI")
        arxiv_id = external.get("ArXiv")
        venue = (
            item.get("venue")
            or (item.get("journal") or {}).get("name")
            or ("arXiv" if arxiv_id else None)
        )
        publication_types = item.get("publicationTypes") or []
        return Paper(
            title=clean_text(item.get("title")) or "Untitled paper",
            abstract=clean_text(item.get("abstract")),
            publication_date=parse_date(item.get("publicationDate")),
            year=item.get("year"),
            venue=clean_text(venue),
            publication_type=", ".join(publication_types) or None,
            doi=doi,
            arxiv_id=arxiv_id,
            biorxiv_doi=doi if doi and str(doi).lower().startswith("10.1101/") else None,
            semantic_scholar_id=item.get("paperId"),
            paper_url=item.get("url") or (f"https://doi.org/{doi}" if doi else ""),
            source=source,
            categories=list(item.get("fieldsOfStudy") or []),
            citation_count=item.get("citationCount"),
            influential_citation_count=item.get("influentialCitationCount"),
        )

    def search(self, queries: list[str], start: date, end: date, limit: int) -> list[Paper]:
        papers: list[Paper] = []
        for query in queries:
            if self._rate_limited:
                break
            try:
                self._throttle()
                payload = self.client.get_json(
                    f"{GRAPH_URL}/paper/search",
                    params={
                        "query": query,
                        "publicationDateOrYear": f"{start.isoformat()}:{end.isoformat()}",
                        "limit": min(limit, 100),
                        "fields": FIELDS,
                    },
                    headers=self.headers,
                )
                papers.extend(self._paper(item) for item in payload.get("data", []))
            except Exception as exc:
                LOGGER.exception("Semantic Scholar query failed", extra={"query": query})
                if self._trip_rate_limit(exc):
                    break
        return papers

    def resolve_seed(self, title: str) -> str | None:
        if self._rate_limited:
            return None
        try:
            self._throttle()
            payload = self.client.get_json(
                f"{GRAPH_URL}/paper/search",
                params={"query": title, "limit": 5, "fields": "title"},
                headers=self.headers,
            )
        except Exception as exc:
            LOGGER.exception("Could not resolve seed", extra={"title": title})
            self._trip_rate_limit(exc)
            return None
        wanted = "".join(title.casefold().split())
        results = payload.get("data", [])
        exact = next(
            (
                item
                for item in results
                if "".join(item.get("title", "").casefold().split()) == wanted
            ),
            None,
        )
        return (exact or (results[0] if results else {})).get("paperId")

    def recommendations(self, seed_ids: list[str], limit_per_seed: int = 50) -> list[Paper]:
        by_id: dict[str, Paper] = {}
        for seed_id in seed_ids:
            if self._rate_limited:
                break
            try:
                self._throttle()
                payload = self.client.get_json(
                    f"{RECOMMEND_URL}/papers/forpaper/{seed_id}",
                    params={"from": "recent", "limit": min(limit_per_seed, 500), "fields": FIELDS},
                    headers=self.headers,
                )
                for rank, item in enumerate(payload.get("recommendedPapers", []), 1):
                    paper = self._paper(item, source="semantic_scholar_recommendation")
                    paper.recommendation_rank = rank
                    key = paper.semantic_scholar_id or paper.canonical_id
                    if key not in by_id or rank < (by_id[key].recommendation_rank or 9999):
                        by_id[key] = paper
            except Exception as exc:
                LOGGER.exception(
                    "Semantic Scholar recommendation failed", extra={"seed_id": seed_id}
                )
                if self._trip_rate_limit(exc):
                    break
        return list(by_id.values())

    def fetch_by_id(self, identifier: str) -> Paper | None:
        if self._rate_limited:
            return None
        try:
            self._throttle()
            item = self.client.get_json(
                f"{GRAPH_URL}/paper/{identifier}", params={"fields": FIELDS}, headers=self.headers
            )
            return self._paper(item)
        except Exception as exc:
            LOGGER.exception(
                "Semantic Scholar metadata fetch failed", extra={"identifier": identifier}
            )
            self._trip_rate_limit(exc)
            return None

    def fetch_batch(self, identifiers: list[str]) -> list[Paper]:
        if not identifiers or self._rate_limited:
            return []
        papers: list[Paper] = []
        for offset in range(0, len(identifiers), 500):
            batch = identifiers[offset : offset + 500]
            try:
                self._throttle()
                response = self.client.request(
                    "POST",
                    f"{GRAPH_URL}/paper/batch",
                    params={"fields": FIELDS},
                    json={"ids": batch},
                    headers=self.headers,
                )
                papers.extend(self._paper(item) for item in response.json() if item)
            except Exception as exc:
                LOGGER.exception("Semantic Scholar batch fetch failed")
                if self._trip_rate_limit(exc):
                    break
        return papers
