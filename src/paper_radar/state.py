from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from paper_radar.dedup import identity_keys
from paper_radar.models import Paper, normalize_title


@dataclass(slots=True)
class SentRecord:
    canonical_id: str
    category: str
    first_sent_at: str
    publication_status: str
    preprint_doi: str | None
    published_doi: str | None
    venue: str | None
    title_key: str
    identity_keys: list[str]


class StateStore:
    def __init__(self, path: Path, retention_days: int = 1825) -> None:
        self.path = path
        self.retention_days = retention_days
        self.records: list[SentRecord] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.records = []
            return
        with self.path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.records = [SentRecord(**item) for item in payload.get("records", [])]

    def _formal_publication_exception(self, paper: Paper, record: SentRecord) -> bool:
        if paper.publication_status != "published" or record.publication_status != "preprint":
            return False
        same_preprint = bool(
            paper.preprint_doi
            and record.preprint_doi
            and paper.preprint_doi.casefold() == record.preprint_doi.casefold()
        )
        same_title = record.title_key == normalize_title(paper.title)
        formal_is_new = bool(paper.published_doi or paper.doi)
        return formal_is_new and (same_preprint or same_title)

    def was_sent(self, paper: Paper, category: str) -> bool:
        current_keys = identity_keys(paper)
        title_key = normalize_title(paper.title)
        for record in self.records:
            if record.category != category:
                continue
            overlaps = (
                bool(current_keys.intersection(record.identity_keys))
                or record.title_key == title_key
            )
            if not overlaps:
                continue
            if self._formal_publication_exception(paper, record):
                continue
            return True
        return False

    def mark_sent(self, paper: Paper, category: str, sent_at: datetime | None = None) -> None:
        if self.was_sent(paper, category):
            return
        now = sent_at or datetime.now(UTC)
        self.records.append(
            SentRecord(
                canonical_id=paper.canonical_id or paper.compute_canonical_id(),
                category=category,
                first_sent_at=now.isoformat(),
                publication_status=paper.publication_status,
                preprint_doi=paper.preprint_doi or paper.biorxiv_doi,
                published_doi=paper.published_doi
                or (paper.doi if paper.publication_status == "published" else None),
                venue=paper.venue,
                title_key=normalize_title(paper.title),
                identity_keys=sorted(identity_keys(paper)),
            )
        )

    def prune(self, today: date | None = None) -> None:
        cutoff = (today or date.today()) - timedelta(days=self.retention_days)
        kept: list[SentRecord] = []
        for record in self.records:
            try:
                sent_date = datetime.fromisoformat(record.first_sent_at).date()
            except ValueError:
                kept.append(record)
                continue
            if sent_date >= cutoff:
                kept.append(record)
        self.records = kept

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "records": [asdict(record) for record in self.records]}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(self.path)


def save_candidate_cache(path: Path, generated_on: date, papers: dict[str, list[Paper]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "generated_on": generated_on.isoformat(),
        "categories": {
            name: [paper.to_dict() for paper in values] for name, values in papers.items()
        },
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def load_candidate_cache(path: Path, category: str) -> list[Paper]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return [Paper.from_dict(item) for item in payload.get("categories", {}).get(category, [])]
