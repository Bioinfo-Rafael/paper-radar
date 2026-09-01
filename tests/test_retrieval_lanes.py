from __future__ import annotations

from datetime import date, timedelta

from paper_radar.models import Rating
from paper_radar.pipeline import Pipeline
from paper_radar.scoring.bioinfo import score_bioinfo
from paper_radar.sources.crossref import CrossrefPreprintSource
from tests.conftest import make_paper, stub_broad_sources


class FakeCrossrefClient:
    def get_json(self, url, **kwargs):
        assert url.endswith("/prefixes/10.64898/works")
        if not url.endswith("/prefixes/10.64898/works"):
            return {"message": {"items": []}}
        return {
            "message": {
                "items": [
                    {
                        "DOI": "10.64898/2026.08.20.746112",
                        "title": [
                            "MultiFlow: coupled flow matching for predicting single-cell "
                            "multiomic perturbation responses in unseen cellular contexts"
                        ],
                        "abstract": (
                            "<jats:p>We present a coupled flow-matching framework that unifies "
                            "generation and perturbation prediction of paired gene expression and "
                            "chromatin accessibility. MultiFlow predicts coordinated multiomic "
                            "responses in unseen cellular contexts across multiple "
                            "benchmarks.</jats:p>"
                        ),
                        "published": {"date-parts": [[2026, 8, 25]]},
                        "URL": "https://doi.org/10.64898/2026.08.20.746112",
                    }
                ]
            }
        }


def test_a_backfill_fills_when_fresh_has_no_qualifying_paper(config, tmp_path, monkeypatch):
    monkeypatch.setitem(config.common["state"], "path", str(tmp_path / "sent.json"))
    pipeline = Pipeline(config)
    fresh_low = make_paper(
        title="Low fresh",
        score=3.0,
        importance_score=3.0,
        retrieval_lane="fresh",
    )
    backfill_good = make_paper(
        title="Important backfill",
        score=7.0,
        importance_score=7.0,
        retrieval_lane="backfill",
    )
    assert pipeline.select_daily("bioinfo", [backfill_good, fresh_low]) == [backfill_good]


def test_b_and_d_old_top_journal_keeps_same_importance_rating(config, today):
    content = {
        "title": "A unified formulation for single-cell perturbation dynamics",
        "abstract": (
            "We introduce a new method and probabilistic model with broad validation "
            "across datasets and unseen conditions."
        ),
        "venue": "Nature Methods",
    }
    fresh = score_bioinfo(
        make_paper(publication_date=today - timedelta(days=4), **content),
        config.category("bioinfo"),
        config.venues["bioinfo"],
        today,
    )
    old = score_bioinfo(
        make_paper(publication_date=today - timedelta(days=300), **content),
        config.category("bioinfo"),
        config.venues["bioinfo"],
        today,
    )
    assert old.importance_score == fresh.importance_score
    assert old.rating is fresh.rating
    assert old.freshness_bonus < fresh.freshness_bonus
    assert not old.excluded


def test_c_multiflow_enters_retrieval_and_scores_as_must_read(config):
    source = CrossrefPreprintSource(FakeCrossrefClient())
    papers = source.fetch(
        date(2026, 8, 1),
        date(2026, 8, 29),
        20,
        ("10.64898",),
        ("transcriptomics multiomics perturbation",),
    )
    assert len(papers) == 1
    paper = score_bioinfo(
        papers[0], config.category("bioinfo"), config.venues["bioinfo"], date(2026, 8, 29)
    )
    assert paper.biorxiv_doi == "10.64898/2026.08.20.746112"
    assert {"single-cell", "perturbation", "generative-modeling", "generalization"}.issubset(
        paper.matched_criteria
    )
    assert not paper.excluded
    assert paper.rating is Rating.MUST_READ


def test_archive_lane_is_bounded_and_only_used_for_top_journals(config, today):
    pipeline = Pipeline(config)
    lanes = pipeline.retrieval_lanes("bioinfo", today)
    assert [(lane.name, (today - lane.start).days) for lane in lanes] == [
        ("fresh", 30),
        ("backfill", 365),
        ("archive", 730),
    ]
    archive = make_paper(
        title="Old top journal method",
        venue="Nature Methods",
        score=8,
        importance_score=8,
        retrieval_lane="archive",
    )
    assert pipeline.select_more("bioinfo", [archive], 5) == [archive]


def test_frontier_has_archive_lane(config, today):
    lanes = Pipeline(config).retrieval_lanes("frontier", today)
    assert [lane.name for lane in lanes] == ["fresh", "backfill", "archive"]
    assert (today - lanes[-1].start).days == 730


def test_frontier_archive_keeps_top_venue_candidate(config, today, monkeypatch):
    pipeline = Pipeline(config)
    stub_broad_sources(monkeypatch)
    top = make_paper(title="Archived embodied agent", venue="NeurIPS")
    ordinary = make_paper(title="Archived embodied agent preprint", venue="arXiv")
    monkeypatch.setattr(pipeline.s2, "search", lambda *args, **kwargs: [top, ordinary])
    lane = next(
        lane for lane in pipeline.retrieval_lanes("frontier", today) if lane.name == "archive"
    )
    groups = pipeline._acquire_lane("frontier", lane, pipeline.search_settings("daily"))
    assert groups["semantic_scholar"] == [top]
    assert top.retrieval_lane == "archive"


def test_frontier_tuned_archive_can_extend_to_1095_days(config, today, monkeypatch):
    monkeypatch.setitem(
        config.tuning,
        "backfill",
        [
            {
                "channel": "frontier",
                "journal_group": "top_journals",
                "journal": None,
                "days": 1095,
                "priority": 1.0,
            }
        ],
    )
    lanes = Pipeline(config).retrieval_lanes("frontier", today)
    assert (today - lanes[-1].start).days == 1095


def test_new_venue_tiers_are_configured(config):
    assert "Nature Computational Science" in config.venues["bioinfo"]["tier_s"]
    assert "Nucleic Acids Research" in config.venues["bioinfo"]["tier_a"]
    assert "COLT" in config.venues["ml"]["top"]
    assert "UAI" in config.venues["ml"]["top"]
    assert "AAMAS" in config.venues["frontier"]["top"]
    assert "IEEE Transactions on Robotics" in config.venues["frontier"]["top"]
    assert "AAAI" in config.venues["frontier"]["strong"]


def test_selection_reserves_space_for_important_history(config, tmp_path, monkeypatch):
    monkeypatch.setitem(config.common["state"], "path", str(tmp_path / "sent.json"))
    pipeline = Pipeline(config)
    fresh = [
        make_paper(
            title=f"Fresh {index}",
            score=10 - index,
            importance_score=10 - index,
            retrieval_lane="fresh",
        )
        for index in range(5)
    ]
    history = [
        make_paper(
            title=f"History {index}",
            score=5 - index,
            importance_score=5 - index,
            retrieval_lane="backfill" if index == 0 else "archive",
        )
        for index in range(2)
    ]
    selected = pipeline.select_daily("bioinfo", [*fresh, *history])
    assert selected == [*fresh[:3], *history]


def test_e_five_star_is_reachable_without_freshness(config, today):
    paper = score_bioinfo(
        make_paper(
            title="A new formulation for single-cell stochastic perturbation dynamics",
            abstract=(
                "We introduce a unified framework and probabilistic model for unseen conditions, "
                "with broad validation across datasets and mechanistic insight."
            ),
            publication_date=today - timedelta(days=500),
            venue="Nature Methods",
        ),
        config.category("bioinfo"),
        config.venues["bioinfo"],
        today,
    )
    assert paper.freshness_bonus == 0
    assert paper.rating is Rating.MUST_READ


def test_f_normal_ranking_does_not_call_groq(config, today, monkeypatch):
    calls = []
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: calls.append((args, kwargs)))
    pipeline = Pipeline(config)
    pipeline.rank(
        "bioinfo",
        [
            make_paper(
                title="A single-cell dynamical model",
                abstract="We introduce a new method and formulation.",
            )
        ],
        today,
    )
    assert calls == []
