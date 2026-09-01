from __future__ import annotations

import logging
import re

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import strip_html

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://papers.nips.cc"
ENTRY = re.compile(r'href="(/paper_files/paper/\d+/hash/[^"]+)">([^<]+)<')


class NeurIPSProceedingsSource:
    """Index-page-only scrape: title/URL/venue, no abstract (thousands of
    papers per year make per-paper detail fetches prohibitively expensive;
    dedup/merge backfills the abstract from a richer source when available).
    """

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, year: int, limit: int = 500) -> list[Paper]:
        url = f"{BASE_URL}/paper_files/paper/{year}"
        try:
            response = self.client.request("GET", url, health_key="neurips_proceedings")
            body = response.text
        except Exception:
            LOGGER.exception("NeurIPS proceedings fetch failed", extra={"year": year})
            return []
        papers: list[Paper] = []
        seen: set[str] = set()
        for href, raw_title in ENTRY.findall(body)[:limit]:
            title = strip_html(raw_title)
            if not title or href in seen:
                continue
            seen.add(href)
            papers.append(
                Paper(
                    title=title,
                    abstract="",
                    year=year,
                    venue="NeurIPS",
                    publication_type="Conference Paper",
                    paper_url=f"{BASE_URL}{href}",
                    source="neurips_proceedings",
                )
            )
        return papers
