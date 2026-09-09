from __future__ import annotations

from pathlib import Path

from extensions.feedback.enrich import run_enrichment
from extensions.feedback.identify import MatchedPaper
from extensions.feedback.state_store import FeedbackStateStore
from paper_radar.models import Paper


def _seed_pending(
    state: FeedbackStateStore, count: int, *, with_identifier: bool = True, prefix: str = "a"
) -> None:
    for i in range(count):
        arxiv_id = f"260{prefix}{i:04d}"
        matched = MatchedPaper(
            canonical_id=f"title:{prefix}{i:04d}" if not with_identifier else f"arxiv:{arxiv_id}",
            title=f"Paper {prefix}{i}",
            paper_url=f"https://arxiv.org/abs/{arxiv_id}",
            abstract="",
            category="ml",
            publication_date=None,
            venue=None,
            score=None,
            rating=None,
            doi=None,
            arxiv_id=arxiv_id if with_identifier else None,
            semantic_scholar_id=None,
            matched_locally=False,
        )
        state.enqueue_pending_abstract(matched)


def _fake_paper(arxiv_id: str, abstract: str = "a fetched abstract") -> Paper:
    return Paper(
        title=f"Paper for {arxiv_id}",
        paper_url=f"https://arxiv.org/abs/{arxiv_id}",
        source="semantic_scholar",
        arxiv_id=arxiv_id,
        abstract=abstract,
    )


def test_batch_fetch_is_skipped_below_the_threshold(tmp_path: Path):
    state = FeedbackStateStore(tmp_path / "state")
    _seed_pending(state, 5)
    calls = []

    def fetch_batch(identifiers):
        calls.append(identifiers)
        return []

    summary = run_enrichment(state, fetch_batch, min_pending=20)
    assert summary.skipped_below_threshold is True
    assert calls == []
    assert len(state.pending_papers()) == 5


def test_force_bypasses_the_threshold(tmp_path: Path):
    state = FeedbackStateStore(tmp_path / "state")
    _seed_pending(state, 5)
    calls = []

    def fetch_batch(identifiers):
        calls.append(identifiers)
        return [_fake_paper(identifier.split(":", 1)[1]) for identifier in identifiers]

    summary = run_enrichment(state, fetch_batch, force=True, min_pending=20)
    assert calls
    assert summary.resolved == 5
    assert state.pending_papers() == {}


def test_api_failure_keeps_every_paper_in_the_chunk_pending(tmp_path: Path):
    state = FeedbackStateStore(tmp_path / "state")
    _seed_pending(state, 21)

    def failing_fetch_batch(identifiers):
        raise RuntimeError("Semantic Scholar unreachable")

    summary = run_enrichment(state, failing_fetch_batch, min_pending=20)
    assert summary.batch_failures >= 1
    assert len(state.pending_papers()) == 21
    for entry in state.pending_papers().values():
        assert entry["attempts"] >= 1
        assert entry["last_error"]


def test_papers_not_found_in_the_response_stay_pending(tmp_path: Path):
    state = FeedbackStateStore(tmp_path / "state")
    _seed_pending(state, 21)

    summary = run_enrichment(state, lambda identifiers: [], min_pending=20)
    assert summary.resolved == 0
    assert summary.still_pending == 21
    assert len(state.pending_papers()) == 21


def test_no_identifier_papers_are_never_sent_to_the_batch_api(tmp_path: Path):
    state = FeedbackStateStore(tmp_path / "state")
    _seed_pending(state, 20, with_identifier=True, prefix="a")
    _seed_pending(state, 5, with_identifier=False, prefix="b")
    seen_ids: list[str] = []

    def fetch_batch(identifiers):
        seen_ids.extend(identifiers)
        return [_fake_paper(identifier.split(":", 1)[1]) for identifier in identifiers]

    summary = run_enrichment(state, fetch_batch, min_pending=20)
    assert summary.no_identifier == 5
    assert len(seen_ids) == 20
    assert summary.resolved == 20
    # the 5 no-identifier papers are still queued, just never sent externally
    assert len(state.pending_papers()) == 5


def test_batches_are_capped_at_max_papers_per_batch(tmp_path: Path):
    state = FeedbackStateStore(tmp_path / "state")
    _seed_pending(state, 120)
    chunk_sizes = []

    def fetch_batch(identifiers):
        chunk_sizes.append(len(identifiers))
        return [_fake_paper(identifier.split(":", 1)[1]) for identifier in identifiers]

    run_enrichment(state, fetch_batch, force=True, min_pending=20, max_papers_per_batch=50)
    assert chunk_sizes
    assert all(size <= 50 for size in chunk_sizes)
    assert sum(chunk_sizes) == 120
