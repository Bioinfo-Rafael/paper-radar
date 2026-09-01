from __future__ import annotations

import logging
import re

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import strip_html

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://proceedings.mlr.press"
PAPER_BLOCK = re.compile(r'<div class="paper">(.*?)</div>', re.S)
TITLE = re.compile(r'<p class="title">(.*?)</p>', re.S)
AUTHORS = re.compile(r'<span class="authors">(.*?)</span>', re.S)
ABS_LINK = re.compile(r'<a href="([^"]+)">abs</a>')


class PMLRSource:
    """Static Jekyll HTML per volume; also covers CoRL, which PMLR publishes."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, volume: int, venue: str, year: int, limit: int = 300) -> list[Paper]:
        url = f"{BASE_URL}/v{volume}/"
        try:
            response = self.client.request("GET", url, health_key="pmlr")
            body = response.text
        except Exception:
            LOGGER.exception("PMLR volume fetch failed", extra={"volume": volume})
            return []
        papers: list[Paper] = []
        for block in PAPER_BLOCK.findall(body)[:limit]:
            title_match = TITLE.search(block)
            if not title_match:
                continue
            title = strip_html(title_match.group(1))
            if not title:
                continue
            authors_match = AUTHORS.search(block)
            authors = (
                [name.strip() for name in strip_html(authors_match.group(1)).split(",") if name]
                if authors_match
                else []
            )
            abs_match = ABS_LINK.search(block)
            paper_url = abs_match.group(1) if abs_match else url
            papers.append(
                Paper(
                    title=title,
                    abstract="",
                    year=year,
                    venue=venue,
                    publication_type="Conference Paper",
                    authors=authors,
                    paper_url=paper_url,
                    source="pmlr",
                )
            )
        return papers
