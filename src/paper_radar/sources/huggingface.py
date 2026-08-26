from __future__ import annotations

import logging
from datetime import date
from typing import Any

from huggingface_hub import HfApi

from paper_radar.models import Paper
from paper_radar.sources.utils import clean_text, parse_date

LOGGER = logging.getLogger(__name__)


def _value(item: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(item, name, None)
        if value is not None:
            return value
        if isinstance(item, dict) and item.get(name) is not None:
            return item[name]
    return default


class HuggingFaceSource:
    def __init__(self) -> None:
        self.api = HfApi()

    def fetch(self, today: date, limit: int = 50) -> list[Paper]:
        iso = today.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        try:
            items = list(
                self.api.list_daily_papers(week=week, sort="trending", limit=limit, token=False)
            )
        except Exception:
            LOGGER.exception("Hugging Face Daily Papers fetch failed")
            return []
        papers: list[Paper] = []
        for rank, item in enumerate(items, 1):
            identifier = str(_value(item, "id", "paper_id", default=""))
            title = clean_text(_value(item, "title", default="Untitled paper"))
            abstract = clean_text(_value(item, "summary", "abstract", default=""))
            published = _value(item, "published_at", "publishedAt")
            if hasattr(published, "date"):
                published = published.date().isoformat()
            arxiv_id = identifier if identifier and identifier[0].isdigit() else None
            papers.append(
                Paper(
                    title=title,
                    abstract=abstract,
                    publication_date=parse_date(str(published) if published else None),
                    venue="arXiv",
                    publication_type="Preprint",
                    arxiv_id=arxiv_id,
                    paper_url=f"https://huggingface.co/papers/{identifier}",
                    source="huggingface",
                    hf_rank=rank,
                )
            )
        return papers
