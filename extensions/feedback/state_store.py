from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from extensions.feedback.events import ReactionEvent, now_iso
from extensions.feedback.identify import MatchedPaper

_META_DEFAULT: dict[str, Any] = {
    "version": 1,
    "last_seen_message_id": {},
    "note": (
        "This store only ever records reactions from one configured "
        "TARGET_USER_ID (see extensions/feedback/config.py). It never "
        "records anyone else's reactions."
    ),
}


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


class FeedbackStateStore:
    """Append-only-friendly JSON/JSONL persistence for the private feedback
    state repository. Every raw event and every shadow prediction is
    appended, never rewritten, so future re-analysis can replay full
    history.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_events_path = root / "raw_events.jsonl"
        self.processed_path = root / "processed_events.json"
        self.pending_path = root / "pending_abstracts.json"
        self.enriched_path = root / "enriched_abstracts.json"
        self.meta_path = root / "meta.json"
        self.predictions_path = root / "shadow_predictions.jsonl"
        self._processed = _read_json(self.processed_path, {"version": 1, "events": {}})
        self._pending = _read_json(self.pending_path, {"version": 1, "papers": {}})
        self._enriched = _read_json(self.enriched_path, {"version": 1, "abstracts": {}})
        self._meta = _read_json(self.meta_path, _META_DEFAULT)

    # -- idempotency -----------------------------------------------------
    def is_processed(self, event_id: str) -> bool:
        return event_id in self._processed["events"]

    def mark_processed(self, event_id: str, forwarded_to: str | None) -> None:
        self._processed["events"][event_id] = {
            "recorded_at": now_iso(),
            "forwarded_to": forwarded_to,
        }
        _write_json(self.processed_path, self._processed)

    # -- raw events (append-only) -----------------------------------------
    def append_raw_event(self, event: ReactionEvent) -> None:
        with self.raw_events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def read_raw_events(self) -> list[dict[str, Any]]:
        if not self.raw_events_path.exists():
            return []
        events = []
        with self.raw_events_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    # -- per-channel cursor ------------------------------------------------
    def last_seen_message_id(self, channel_id: str) -> str | None:
        return self._meta["last_seen_message_id"].get(channel_id)

    def set_last_seen_message_id(self, channel_id: str, message_id: str) -> None:
        self._meta["last_seen_message_id"][channel_id] = message_id
        _write_json(self.meta_path, self._meta)

    # -- pending abstract queue --------------------------------------------
    def enqueue_pending_abstract(self, matched: MatchedPaper) -> None:
        papers = self._pending["papers"]
        entry = papers.get(matched.canonical_id)
        if entry is None:
            entry = {
                "canonical_id": matched.canonical_id,
                "title": matched.title,
                "paper_url": matched.paper_url,
                "doi": matched.doi,
                "arxiv_id": matched.arxiv_id,
                "semantic_scholar_id": matched.semantic_scholar_id,
                "first_queued_at": now_iso(),
                "attempts": 0,
                "last_attempt_at": None,
                "last_error": None,
            }
        else:
            entry["doi"] = entry.get("doi") or matched.doi
            entry["arxiv_id"] = entry.get("arxiv_id") or matched.arxiv_id
            entry["semantic_scholar_id"] = entry.get("semantic_scholar_id") or (
                matched.semantic_scholar_id
            )
        papers[matched.canonical_id] = entry
        _write_json(self.pending_path, self._pending)

    def pending_papers(self) -> dict[str, dict[str, Any]]:
        return dict(self._pending["papers"])

    def remove_pending(self, canonical_id: str) -> None:
        if self._pending["papers"].pop(canonical_id, None) is not None:
            _write_json(self.pending_path, self._pending)

    def record_pending_attempt(self, canonical_id: str, error: str | None) -> None:
        entry = self._pending["papers"].get(canonical_id)
        if entry is None:
            return
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_attempt_at"] = now_iso()
        entry["last_error"] = error
        _write_json(self.pending_path, self._pending)

    # -- enriched abstract cache -------------------------------------------
    def save_enriched_abstract(self, canonical_id: str, abstract: str, source: str) -> None:
        self._enriched["abstracts"][canonical_id] = {
            "abstract": abstract,
            "source": source,
            "fetched_at": now_iso(),
        }
        _write_json(self.enriched_path, self._enriched)

    def get_enriched_abstract(self, canonical_id: str) -> str | None:
        entry = self._enriched["abstracts"].get(canonical_id)
        return entry["abstract"] if entry else None

    # -- shadow predictions (append-only) ----------------------------------
    def append_predictions(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.predictions_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
