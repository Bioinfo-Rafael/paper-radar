from __future__ import annotations

from paper_radar.focus import apply_focus_bonus, resolve_focus
from paper_radar.pipeline import Pipeline
from paper_radar.scoring.ai_frontier import score_frontier
from tests.conftest import make_paper, stub_broad_sources


def test_physical_ai_focus_resolves_family_and_aliases(config):
    spec = resolve_focus("Physical-AI", config.category("frontier"))
    assert spec is not None
    assert spec.families == ("physical-ai",)
    assert {"physical AI", "embodied AI", "embodied intelligence"}.issubset(spec.queries)


def test_focus_changes_selection_score_but_not_importance_or_rating(config, today):
    paper = score_frontier(
        make_paper(
            title="A world model for embodied intelligence",
            abstract="A new paradigm with generalization to unseen environments.",
            venue="arXiv",
        ),
        config.category("frontier"),
        today,
        config.venues["frontier"],
    )
    before = (paper.importance_score, paper.rating, paper.score)
    spec = resolve_focus("Physical AI", config.category("frontier"))
    apply_focus_bonus(
        paper,
        spec,
        config.category("frontier")["thresholds"],
        config.common["search"]["focus"],
    )
    assert (paper.importance_score, paper.rating) == before[:2]
    assert paper.focus_bonus == 2.0
    assert paper.score == before[2] + 2.0


def test_known_focus_does_not_match_on_generic_ai_token(config, today):
    paper = score_frontier(
        make_paper(
            title="A memory system for AI",
            abstract="A memory architecture for language models.",
        ),
        config.category("frontier"),
        today,
        config.venues["frontier"],
    )
    spec = resolve_focus("Physical AI", config.category("frontier"))
    apply_focus_bonus(
        paper,
        spec,
        config.category("frontier")["thresholds"],
        config.common["search"]["focus"],
    )
    assert paper.focus_bonus == 0
    assert "physical-ai" not in paper.matched_criteria


def test_unknown_focus_is_added_as_best_effort_query(config, today, monkeypatch):
    pipeline = Pipeline(config)
    calls = []
    monkeypatch.setattr(
        pipeline.s2,
        "search",
        lambda queries, start, end, limit: calls.append(list(queries)) or [],
    )
    stub_broad_sources(monkeypatch)
    spec = resolve_focus(
        "robot learning from interventions", config.category("frontier")
    )
    lane = next(
        lane for lane in pipeline.retrieval_lanes("frontier", today) if lane.name == "backfill"
    )
    pipeline._acquire_lane("frontier", lane, pipeline.search_settings("more"), spec)
    assert "robot learning from interventions" in calls[0]


def test_more_focus_does_not_call_groq(config, today, monkeypatch):
    calls = []
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: calls.append((args, kwargs)))
    pipeline = Pipeline(config)
    spec = resolve_focus("world model", config.category("frontier"))
    pipeline.rank(
        "frontier",
        [make_paper(title="A world model", abstract="A world model for control.")],
        today,
        spec,
    )
    assert calls == []
