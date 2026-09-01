from __future__ import annotations

import logging
import re

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import strip_html

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://openaccess.thecvf.com"
ENTRY = re.compile(r'<dt class="ptitle">.*?<a href="([^"]+)">([^<]+)</a>', re.S)


class CVFSource:
    """CVF Open Access: single index page per conference/year (day=all).

    Title/URL/venue only, same cost trade-off as NeurIPSProceedingsSource.
    """

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, conference: str, year: int, limit: int = 1500) -> list[Paper]:
        url = f"{BASE_URL}/{conference}{year}?day=all"
        try:
            response = self.client.request("GET", url, health_key="cvf")
            body = response.text
        except Exception:
            LOGGER.exception("CVF fetch failed", extra={"conference": conference, "year": year})
            return []
        papers: list[Paper] = []
        seen: set[str] = set()
        for href, raw_title in ENTRY.findall(body)[:limit]:
            title = strip_html(raw_title)
            if not title or href in seen:
                continue
            seen.add(href)
            paper_url = f"{BASE_URL}{href}" if href.startswith("/") else href
            papers.append(
                Paper(
                    title=title,
                    abstract="",
                    year=year,
                    venue=conference,
                    publication_type="Conference Paper",
                    paper_url=paper_url,
                    source="cvf",
                )
            )
        return papers
