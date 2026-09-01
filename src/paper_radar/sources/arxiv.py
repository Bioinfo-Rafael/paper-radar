from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urlencode

import feedparser

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text, parse_date

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://export.arxiv.org/api/query"


class ArxivSource:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, categories: list[str], start: date, end: date, limit: int) -> list[Paper]:
        categories_query = " OR ".join(f"cat:{category}" for category in categories)
        date_query = (
            f"submittedDate:[{start.strftime('%Y%m%d')}0000 TO {end.strftime('%Y%m%d')}2359]"
        )
        query = f"({categories_query}) AND {date_query}"
        params = {
            "search_query": query,
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{BASE_URL}?{urlencode(params)}"
        try:
            response = self.client.request("GET", url)
            feed = feedparser.parse(response.content)
        except Exception:
            LOGGER.exception("arXiv fetch failed")
            return []
        papers: list[Paper] = []
        for entry in feed.entries:
            publication_date = parse_date(getattr(entry, "published", None))
            if publication_date and not start <= publication_date <= end:
                continue
            identifier = re.sub(r"v\d+$", "", entry.id.rsplit("/", 1)[-1])
            category_values = [tag.term for tag in getattr(entry, "tags", [])]
            venue = "arXiv"
            journal_ref = getattr(entry, "arxiv_journal_ref", None)
            doi = getattr(entry, "arxiv_doi", None)
            if journal_ref:
                venue = clean_text(journal_ref)
            authors = [
                clean_text(author.get("name", "")) for author in getattr(entry, "authors", [])
            ]
            papers.append(
                Paper(
                    title=clean_text(entry.title),
                    abstract=clean_text(entry.summary),
                    publication_date=publication_date,
                    venue=venue,
                    publication_type="Preprint",
                    doi=doi,
                    arxiv_id=identifier,
                    authors=[name for name in authors if name],
                    paper_url=f"https://arxiv.org/abs/{identifier}",
                    source="arxiv",
                    categories=category_values,
                )
            )
        return papers
