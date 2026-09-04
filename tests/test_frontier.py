from __future__ import annotations

from datetime import date, timedelta

from paper_radar.models import Rating
from paper_radar.scoring.ai_frontier import score_frontier
from tests.conftest import make_paper


def scored(config, today, **values):
    values.setdefault("venue", "arXiv")
    return score_frontier(
        make_paper(**values), config.category("frontier"), today, config.venues["frontier"]
    )


def test_high_rank_world_model_and_agent(config, today):
    world = scored(
        config,
        today,
        hf_rank=2,
        title="A world model for embodied AI",
        abstract=(
            "First demonstration of generalization to an unseen environment "
            "with long-horizon autonomy."
        ),
    )
    agent = scored(
        config,
        today,
        hf_rank=4,
        title="A self-improving AI agent",
        abstract=(
            "The autonomous agent achieves persistent improvement from experience "
            "and transfer of self-improvement."
        ),
    )
    assert world.rating is Rating.MUST_READ
    assert agent.rating is Rating.MUST_READ


def test_hf_rank_is_discovery_not_scientific_importance(config, today):
    paper = scored(
        config,
        today,
        hf_rank=1,
        title="A world model",
        abstract="A world model for robot control.",
    )
    assert paper.score_components["hf_trending"] == 1.2
    assert paper.discovery_bonus == 1.2
    assert paper.importance_score == 2.2
    assert paper.rating is Rating.BELOW


def test_pure_generation_excluded(config, today):
    paper = scored(
        config,
        today,
        hf_rank=1,
        title="High fidelity video generation",
        abstract="A new architecture for pure video generation.",
    )
    assert paper.excluded


def test_secondary_low_rank_excluded_and_top_breakthrough_included(config, today):
    low = scored(
        config,
        today,
        hf_rank=30,
        title="Reasoning with test-time compute",
        abstract="A benchmark improvement for reasoning.",
    )
    high = scored(
        config,
        today,
        hf_rank=1,
        title="A new paradigm for foundation model reasoning",
        abstract=(
            "Previously impossible capability and qualitative capability change on unseen tasks."
        ),
    )
    assert low.excluded
    assert high.rating is Rating.STRONG


def test_old_paper_legendary_path(config, today):
    old_date = date(2019, 1, 1)
    ordinary = scored(
        config,
        today,
        publication_date=old_date,
        hf_rank=3,
        title="An old world model",
        abstract="A world model.",
        citation_count=50,
    )
    legendary = scored(
        config,
        today,
        publication_date=old_date,
        hf_rank=2,
        title="A legendary world model",
        abstract="A world model and new paradigm for embodied AI.",
        citation_count=3000,
        influential_citation_count=300,
    )
    assert ordinary.excluded
    assert not legendary.excluded
    assert "resurfaced/legendary" in legendary.matched_criteria


def test_ordinary_venue_beyond_trending_window_is_excluded(config, today):
    """Papers older than ~2-3 months need an elite venue or top-1% HF
    trending rank to survive -- an ordinary top/strong venue is not enough.
    """
    paper = scored(
        config,
        today,
        publication_date=date(2024, 3, 1),
        title="A world model for embodied AI",
        abstract="A new paradigm with generalization to unseen environments.",
        venue="NeurIPS",
    )
    assert paper.excluded
    assert "old-outside-trending-window" in paper.penalties


def test_recent_ordinary_venue_within_trending_window_is_not_excluded(config, today):
    paper = scored(
        config,
        today,
        publication_date=today - timedelta(days=60),
        title="A world model for embodied AI",
        abstract="A new paradigm with generalization to unseen environments.",
        venue="arXiv",
    )
    assert not paper.excluded


def test_elite_venue_survives_beyond_trending_window(config, today):
    paper = scored(
        config,
        today,
        publication_date=date(2024, 3, 1),
        title="A world model for embodied AI",
        abstract="A new paradigm with generalization to unseen environments.",
        venue="Nature Machine Intelligence",
    )
    assert not paper.excluded
    assert "elite-venue-despite-age" in paper.matched_criteria


def test_top_1pct_trending_survives_beyond_trending_window(config, today):
    paper = scored(
        config,
        today,
        publication_date=date(2024, 3, 1),
        hf_rank=1,
        title="A world model for embodied AI",
        abstract="A new paradigm with generalization to unseen environments.",
    )
    assert not paper.excluded
    assert "top-1pct-trending-despite-age" in paper.matched_criteria


def test_hf_rank_two_does_not_count_as_top_1pct_trending(config, today):
    paper = scored(
        config,
        today,
        publication_date=date(2024, 3, 1),
        hf_rank=2,
        title="A world model for embodied AI",
        abstract="A new paradigm with generalization to unseen environments.",
    )
    assert paper.excluded
    assert "old-outside-trending-window" in paper.penalties
