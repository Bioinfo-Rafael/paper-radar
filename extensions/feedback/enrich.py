from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extensions.feedback.state_store import FeedbackStateStore
from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.semantic_scholar import SemanticScholarSource

LOGGER = logging.getLogger(__name__)

MIN_PENDING_FOR_AUTO_RUN = 20
MAX_PAPERS_PER_BATCH = 50


@dataclass(slots=True)
class EnrichmentSummary:
    resolved: int = 0
    still_pending: int = 0
    no_identifier: int = 0
    batches_attempted: int = 0
    batch_failures: int = 0
    skipped_below_threshold: bool = False
    errors: list[str] = field(default_factory=list)


def _s2_identifier(entry: dict[str, Any]) -> str | None:
    if entry.get("semantic_scholar_id"):
        return str(entry["semantic_scholar_id"])
    if entry.get("doi"):
        return f"DOI:{entry['doi']}"
    if entry.get("arxiv_id"):
        return f"ARXIV:{entry['arxiv_id']}"
    return None


def _matches(entry: dict[str, Any], paper: Paper) -> bool:
    if entry.get("semantic_scholar_id") and paper.semantic_scholar_id:
        return entry["semantic_scholar_id"] == paper.semantic_scholar_id
    if entry.get("doi") and paper.doi:
        return entry["doi"] == paper.doi
    if entry.get("arxiv_id") and paper.arxiv_id:
        return entry["arxiv_id"] == paper.arxiv_id
    return False


def run_enrichment(
    state: FeedbackStateStore,
    fetch_batch: Any,
    *,
    force: bool = False,
    min_pending: int = MIN_PENDING_FOR_AUTO_RUN,
    max_papers_per_batch: int = MAX_PAPERS_PER_BATCH,
) -> EnrichmentSummary:
    """``fetch_batch`` is ``SemanticScholarSource(client).fetch_batch`` (or a
    test double with the same signature): identifiers in, Paper list out.
    One HTTP call per chunk of up to ``max_papers_per_batch`` papers — never
    one external request per reaction.
    """
    summary = EnrichmentSummary()
    pending = state.pending_papers()
    resolvable = {
        canonical_id: (entry, _s2_identifier(entry))
        for canonical_id, entry in pending.items()
    }
    with_identifier = {cid: v for cid, v in resolvable.items() if v[1]}
    summary.no_identifier = len(resolvable) - len(with_identifier)
    if not with_identifier:
        return summary
    if not force and len(with_identifier) < min_pending:
        summary.skipped_below_threshold = True
        return summary

    items = list(with_identifier.items())
    for offset in range(0, len(items), max_papers_per_batch):
        chunk = items[offset : offset + max_papers_per_batch]
        identifiers = [identifier for _, (_, identifier) in chunk]
        summary.batches_attempted += 1
        try:
            papers = fetch_batch(identifiers)
        except Exception as exc:
            LOGGER.exception("Abstract batch fetch failed; keeping papers pending for retry")
            summary.batch_failures += 1
            summary.errors.append(str(exc))
            for canonical_id, _ in chunk:
                state.record_pending_attempt(canonical_id, error=f"batch_request_failed: {exc}")
                summary.still_pending += 1
            continue
        for canonical_id, (entry, _identifier) in chunk:
            match = next((p for p in papers if _matches(entry, p)), None)
            if match is not None and match.abstract:
                state.save_enriched_abstract(canonical_id, match.abstract, "semantic_scholar_batch")
                state.remove_pending(canonical_id)
                summary.resolved += 1
            else:
                reason = "not_found_in_response" if match is None else "no_abstract_available"
                state.record_pending_attempt(canonical_id, error=reason)
                summary.still_pending += 1
    return summary


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    parser = argparse.ArgumentParser(prog="feedback-enrich")
    parser.add_argument("--force", action="store_true", default=False)
    parser.add_argument("--state-dir", default=os.getenv("FEEDBACK_STATE_DIR", "feedback-state"))
    args = parser.parse_args(argv)
    force = args.force or os.getenv("FEEDBACK_ENRICH_FORCE", "").lower() in {"1", "true", "yes"}
    state = FeedbackStateStore(Path(args.state_dir))
    client = HttpClient(timeout=25, retries=4)
    source = SemanticScholarSource(client)
    try:
        summary = run_enrichment(state, source.fetch_batch, force=force)
    except Exception:
        LOGGER.exception("Abstract enrichment failed for this run; pending queue left untouched")
        return 0
    if summary.skipped_below_threshold:
        LOGGER.info("Pending abstract queue below threshold; skipping batch fetch: %s", summary)
    else:
        LOGGER.info("Abstract enrichment summary: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
