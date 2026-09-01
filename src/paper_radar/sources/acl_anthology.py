from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://raw.githubusercontent.com/acl-org/acl-anthology/master/data/xml"


class ACLAnthologySource:
    """Canonical per-venue-year XML (not HTML scraping); includes abstracts."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, venue_code: str, venue_label: str, year: int, limit: int = 500) -> list[Paper]:
        url = f"{BASE_URL}/{year}.{venue_code}.xml"
        try:
            response = self.client.request("GET", url, health_key="acl_anthology")
            root = ET.fromstring(response.content)
        except Exception:
            LOGGER.exception(
                "ACL Anthology fetch failed", extra={"venue_code": venue_code, "year": year}
            )
            return []
        papers: list[Paper] = []
        for paper in root.findall(".//paper")[:limit]:
            title_node = paper.find("title")
            title = clean_text("".join(title_node.itertext())) if title_node is not None else ""
            if not title:
                continue
            authors = []
            for author in paper.findall("author"):
                first = author.findtext("first") or ""
                last = author.findtext("last") or ""
                name = clean_text(f"{first} {last}")
                if name:
                    authors.append(name)
            anthology_id = (paper.findtext("url") or "").strip()
            papers.append(
                Paper(
                    title=title,
                    abstract=clean_text(paper.findtext("abstract") or ""),
                    year=year,
                    venue=venue_label,
                    publication_type="Conference Paper",
                    doi=paper.findtext("doi"),
                    authors=authors,
                    paper_url=(
                        f"https://aclanthology.org/{anthology_id}/"
                        if anthology_id
                        else "https://aclanthology.org/"
                    ),
                    source="acl_anthology",
                )
            )
        return papers
