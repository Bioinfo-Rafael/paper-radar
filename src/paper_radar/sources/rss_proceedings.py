from __future__ import annotations

import logging
import re

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import strip_html

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://www.roboticsconference.org"
LISTING_URL = f"{BASE_URL}/program/papers/"
ROW = re.compile(r'<tr session="[^"]*">(.*?)</tr>', re.S)
TITLE_LINK = re.compile(r'<a href="(/program/papers/\d+/)">\s*<b>(.*?)</b>', re.S)
AUTHOR_CELL = re.compile(r'</a>\s*</td>\s*<td[^>]*>\s*(.*?)\s*<div', re.S)


class RSSProceedingsSource:
    """The listing reflects the currently-accepted RSS cycle (no per-year
    archive is exposed by this domain); title+authors only, no DOI/abstract.
    """

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, year: int | None = None, limit: int = 500) -> list[Paper]:
        try:
            response = self.client.request("GET", LISTING_URL, health_key="rss_proceedings")
            body = response.text
        except Exception:
            LOGGER.exception("RSS proceedings fetch failed")
            return []
        papers: list[Paper] = []
        seen: set[str] = set()
        for row in ROW.findall(body)[:limit]:
            title_match = TITLE_LINK.search(row)
            if not title_match:
                continue
            href, raw_title = title_match.groups()
            title = strip_html(raw_title)
            if not title or href in seen:
                continue
            seen.add(href)
            author_match = AUTHOR_CELL.search(row)
            authors = (
                [name.strip() for name in strip_html(author_match.group(1)).split(",") if name]
                if author_match
                else []
            )
            papers.append(
                Paper(
                    title=title,
                    abstract="",
                    year=year,
                    venue="RSS",
                    publication_type="Conference Paper",
                    authors=authors,
                    paper_url=f"{BASE_URL}{href}",
                    source="rss_proceedings",
                )
            )
        return papers
