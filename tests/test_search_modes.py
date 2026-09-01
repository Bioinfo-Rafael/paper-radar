from __future__ import annotations

from datetime import timedelta

import pytest

from paper_radar.models import Rating
from paper_radar.pipeline import Pipeline
from paper_radar.scoring.common import apply_rating
from tests.conftest import make_paper, stub_broad_sources


@pytest.fixture
def pipeline(config, tmp_path, monkeypatch):
    monkeypatch.setitem(config.common["state"], "path", str(tmp_path / "sent.json"))
    monkeypatch.setitem(
        config.common["state"], "candidate_cache", str(tmp_path / "candidates.json")
    )
    return Pipeline(config)


def eligible_paper(number: int, score: float = 5.0, rating=Rating.CANDIDATE):
    return make_paper(
        title=f"Eligible paper {number}",
        canonical_id=f"doi:eligible-{number}",
        score=score,
        rating=rating,
    )


def test_daily_uses_five_paper_target_and_quality_threshold(pipeline):
    strong = [eligible_paper(i, 6.5, Rating.STRONG) for i in range(8)]
    candidates = [eligible_paper(i + 20, 4.8, Rating.CANDIDATE) for i in range(4)]
    below = eligible_paper(99, 3.999, Rating.BELOW)
    selected = pipeline.select_daily("bioinfo", strong + candidates + [below])
    assert selected == strong[:5]


def test_candidate_rating_boundaries(config):
    thresholds = config.category("bioinfo")["thresholds"]
    candidate = make_paper(score_components={"test": thresholds["more_min_score"]})
    below = make_paper(
        title="Below",
        score_components={"test": thresholds["more_min_score"] - 0.001},
    )
    apply_rating(candidate, thresholds)
    apply_rating(below, thresholds)
    assert candidate.rating is Rating.CANDIDATE
    assert below.rating is Rating.BELOW


def test_more_runs_fresh_acquisition_without_candidate_cache(pipeline, today, monkeypatch):
    calls = []
    papers = [eligible_paper(1)]

    def acquire(category, run_date, mode="daily"):
        calls.append((category, run_date, mode))
        return papers, {"fresh_source": 1}

    monkeypatch.setattr(pipeline, "acquire", acquire)
    monkeypatch.setattr(pipeline, "rank", lambda category, values, run_date: values)
    monkeypatch.setattr(
        "paper_radar.pipeline.load_candidate_cache",
        lambda *args: pytest.fail("/more must not read the daily candidate cache"),
    )
    result = pipeline.run_more("bioinfo", today, 5)
    assert calls == [("bioinfo", today, "more")]
    assert result.selected == papers
    assert result.source_counts == {"fresh_source": 1}


def test_more_uses_wider_lookback_and_larger_source_limits(pipeline, today, monkeypatch):
    stub_broad_sources(monkeypatch)
    arxiv_calls = []
    s2_calls = []
    recommendation_limits = []

    class FakeArxiv:
        def __init__(self, client):
            pass

        def fetch(self, categories, start, end, limit):
            arxiv_calls.append((start, end, limit))
            return []

    def search(queries, start, end, limit):
        s2_calls.append((start, end, limit))
        return []

    def recommendations(seed_ids, limit):
        recommendation_limits.append(limit)
        return []

    monkeypatch.setattr("paper_radar.pipeline.ArxivSource", FakeArxiv)
    monkeypatch.setattr(pipeline.s2, "search", search)
    monkeypatch.setattr(pipeline.s2, "recommendations", recommendations)

    pipeline.acquire("ml", today, mode="daily")
    pipeline.acquire("ml", today, mode="more")

    assert arxiv_calls[0] == (today - timedelta(days=30), today, 350)
    assert arxiv_calls[1] == (
        today - timedelta(days=30), today, 120
    )
    assert arxiv_calls[2] == (
        today - timedelta(days=365),
        today - timedelta(days=31),
        350,
    )
    assert arxiv_calls[3] == (
        today - timedelta(days=365),
        today - timedelta(days=31),
        120,
    )
    assert arxiv_calls[4] == (today - timedelta(days=30), today, 1050)
    assert arxiv_calls[5] == (today - timedelta(days=30), today, 360)
    assert s2_calls[0][2] == 35
    assert s2_calls[4][2] == 105
    assert recommendation_limits == [50, 150]


def test_ml_has_dedicated_stat_ml_retrieval_and_deduplicates(pipeline, today, monkeypatch):
    stub_broad_sources(monkeypatch)
    calls = []
    paper = eligible_paper(101)
    paper.arxiv_id = "2608.12345"

    class FakeArxiv:
        def __init__(self, client):
            pass

        def fetch(self, categories, start, end, limit):
            calls.append((categories, limit))
            return [paper]

    monkeypatch.setattr("paper_radar.pipeline.ArxivSource", FakeArxiv)
    monkeypatch.setattr(pipeline.s2, "search", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline.s2, "recommendations", lambda *args, **kwargs: [])
    candidates, _ = pipeline.acquire("ml", today, mode="daily")
    assert calls[:2] == [
        (["cs.LG", "stat.ML", "cs.AI", "cs.CL", "cs.CV"], 350),
        (["stat.ML"], 120),
    ]
    assert len([candidate for candidate in candidates if candidate.arxiv_id == "2608.12345"]) == 1


def test_more_excludes_sent_and_consecutive_calls_return_different_papers(pipeline):
    ranked = [eligible_paper(i) for i in range(8)]
    first = pipeline.select_more("bioinfo", ranked, 5)
    assert first == ranked[:5]
    for paper in first:
        pipeline.state.mark_sent(paper, "bioinfo")
    second = pipeline.select_more("bioinfo", ranked, 5)
    assert second == ranked[5:]
    assert not set(p.canonical_id for p in first).intersection(p.canonical_id for p in second)


def test_more_count_shortage_zero_and_hard_exclusions(pipeline):
    allowed = [eligible_paper(i) for i in range(3)]
    excluded = eligible_paper(10)
    excluded.excluded = True
    excluded.rating = Rating.EXCLUDED
    low = eligible_paper(11, 3.7, Rating.BELOW)
    ranked = allowed + [excluded, low]
    assert pipeline.select_more("bioinfo", ranked, 2) == allowed[:2]
    assert pipeline.select_more("bioinfo", ranked, 5) == allowed
    assert pipeline.select_more("bioinfo", [excluded, low], 5) == []
    assert excluded not in pipeline.select_daily("bioinfo", ranked)


def test_daily_and_more_call_the_same_rank_method(pipeline, today, monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline,
        "acquire",
        lambda category, run_date, mode="daily": ([], {mode: 0}),
    )

    def rank(category, papers, run_date):
        calls.append((category, run_date))
        return papers

    monkeypatch.setattr(pipeline, "rank", rank)
    pipeline.run_daily("ml", today)
    pipeline.run_more("ml", today, 5)
    assert calls == [("ml", today), ("ml", today)]


def test_workflows_share_state_concurrency_group(config):
    daily = (config.root / ".github/workflows/daily.yml").read_text()
    more = (config.root / ".github/workflows/more.yml").read_text()
    expected = "group: paper-radar-state"
    assert expected in daily
    assert expected in more
    assert "cancel-in-progress: false" in daily
    assert "cancel-in-progress: false" in more
