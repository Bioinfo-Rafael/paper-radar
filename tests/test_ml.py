from __future__ import annotations

import pytest

from paper_radar.models import Rating
from paper_radar.scoring.ml_algorithms import score_ml
from tests.conftest import make_paper


def scored(config, today, **values):
    venue = values.pop("venue", "arXiv")
    return score_ml(
        make_paper(venue=venue, **values), config.category("ml"), config.venues["ml"], today
    )


@pytest.mark.parametrize(
    ("title", "abstract"),
    [
        (
            "A new probability path for diffusion models",
            "We propose a new formulation and sampling process with a new objective across tasks.",
        ),
        (
            "Phase transitions inside diffusion models",
            "We observe an empirical phenomenon and discover an internal mechanism "
            "with a mathematical explanation and design implication.",
        ),
        (
            "A general-purpose state space architecture",
            "We introduce a new architecture and training objective "
            "that changes behavior across tasks.",
        ),
    ],
)
def test_actionable_ml_is_high(config, today, title, abstract):
    paper = scored(config, today, title=title, abstract=abstract)
    assert paper.rating in {Rating.MUST_READ, Rating.STRONG}


@pytest.mark.parametrize(
    ("title", "abstract", "categories"),
    [
        (
            "A new benchmark with SOTA by 2%",
            "We release a dataset and improve accuracy by 2%.",
            ["cs.LG"],
        ),
        (
            "Transformer for medical image diagnosis",
            "An application of a transformer for medical imaging.",
            ["cs.CV"],
        ),
        (
            "A faster CUDA kernel",
            "Our GPU kernel gives memory optimization and slight improvement.",
            ["cs.LG"],
        ),
    ],
)
def test_non_actionable_ml_is_low(config, today, title, abstract, categories):
    paper = scored(config, today, title=title, abstract=abstract, categories=categories)
    assert paper.rating is Rating.BELOW or paper.excluded


def test_pure_theory_low_but_explanatory_theory_positive(config, today):
    pure = scored(
        config,
        today,
        title="A convergence theorem for neural networks",
        abstract="We prove a theorem with a theoretical analysis.",
    )
    connected = scored(
        config,
        today,
        venue="ICLR",
        title="Why neural networks undergo phase transitions",
        abstract=(
            "We observe an empirical phenomenon and provide a mathematical explanation, "
            "internal mechanism, and design implication."
        ),
    )
    assert pure.rating is Rating.BELOW
    assert connected.rating in {Rating.MUST_READ, Rating.STRONG}
