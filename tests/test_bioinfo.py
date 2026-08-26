from __future__ import annotations

import pytest

from paper_radar.models import Rating
from paper_radar.scoring.bioinfo import score_bioinfo
from paper_radar.state import StateStore
from tests.conftest import make_paper


def scored(config, today, **values):
    return score_bioinfo(
        make_paper(**values), config.category("bioinfo"), config.venues["bioinfo"], today
    )


@pytest.mark.parametrize(
    ("title", "abstract"),
    [
        (
            "RegVelo: gene regulatory networks for RNA velocity",
            "We introduce a dynamical model with a latent state and vector field "
            "for single-cell dynamics.",
        ),
        (
            "scDiffusion: generative modeling of single-cell data",
            "We propose a diffusion model formulation with a stochastic process "
            "and new objective function.",
        ),
    ],
)
def test_core_methods_score_high(config, today, title, abstract):
    paper = scored(config, today, title=title, abstract=abstract)
    assert paper.rating in {Rating.MUST_READ, Rating.STRONG}
    assert paper.score_components["formulation_signal"] > 0


def test_specialist_method_survives_venue(config, today):
    paper = scored(
        config,
        today,
        venue="Bioinformatics",
        title="A probabilistic model for single-cell trajectory inference",
        abstract=(
            "We introduce a new method using a latent variable and differential equation "
            "for cellular dynamics."
        ),
    )
    assert paper.rating in {Rating.MUST_READ, Rating.STRONG}
    assert not paper.excluded


@pytest.mark.parametrize(
    ("title", "abstract", "penalty"),
    [
        (
            "A cancer cell atlas in Nature",
            "We construct a cell atlas from a patient cohort using scRNA-seq.",
            "application-only-without-method-development",
        ),
        (
            "CellChat analysis of tumors",
            "Using CellChat, we study a cancer dataset.",
            "application-only-without-method-development",
        ),
        (
            "A reference cell atlas",
            "Atlas construction from single-cell samples.",
            "application-only-without-method-development",
        ),
    ],
)
def test_application_only_excluded(config, today, title, abstract, penalty):
    paper = scored(config, today, venue="Nature", title=title, abstract=abstract)
    assert paper.excluded
    assert penalty in paper.penalties


def test_annotation_with_new_formulation_not_hard_excluded(config, today):
    paper = scored(
        config,
        today,
        title="A new probabilistic model for cell-type annotation",
        abstract=(
            "We propose a latent variable formulation and objective function "
            "for single-cell inference."
        ),
    )
    assert not paper.excluded
    assert paper.score_components["formulation_signal"] > 0


def test_spatial_rules(config, today):
    method = scored(
        config,
        today,
        venue="Nature Methods",
        title="A new spatial transcriptomics method",
        abstract=(
            "We introduce a probabilistic model and new formulation "
            "for spatial transcriptomics inference."
        ),
    )
    application = scored(
        config,
        today,
        venue="Nature",
        title="Spatial transcriptomics of cancer",
        abstract="A case study of a patient cohort and tumor microenvironment.",
    )
    minor = scored(
        config,
        today,
        venue="BMC Bioinformatics",
        title="Spatial transcriptomics tool",
        abstract="We introduce a visualization tool for spatial transcriptomics.",
    )
    assert method.rating in {Rating.MUST_READ, Rating.STRONG}
    assert application.excluded
    assert minor.rating is Rating.BELOW or minor.excluded


def test_foundation_model_venue_rules(config, today):
    top = scored(
        config,
        today,
        venue="Nature Methods",
        title="A single-cell foundation model",
        abstract=(
            "We introduce a new architecture and latent representation "
            "for single-cell perturbation prediction."
        ),
    )
    minor = scored(
        config,
        today,
        venue="bioRxiv",
        title="A single-cell foundation model application",
        abstract="We apply a pretrained model to a cancer dataset.",
    )
    assert top.rating in {Rating.MUST_READ, Rating.STRONG}
    assert minor.rating is Rating.BELOW or minor.excluded


def test_review_excluded(config, today):
    paper = scored(config, today, publication_type="Review", title="Review of RNA velocity")
    assert paper.excluded


def test_formal_publication_is_second_event(tmp_path):
    store = StateStore(tmp_path / "sent.json")
    preprint = make_paper(
        title="Same method", biorxiv_doi="10.1101/abc", preprint_doi="10.1101/abc"
    )
    formal = make_paper(
        title="Same method",
        venue="Nature Methods",
        doi="10.1000/formal",
        biorxiv_doi="10.1101/abc",
        preprint_doi="10.1101/abc",
        published_doi="10.1000/formal",
    )
    store.mark_sent(preprint, "bioinfo")
    assert not store.was_sent(formal, "bioinfo")
    store.mark_sent(formal, "bioinfo")
    assert store.was_sent(formal, "bioinfo")
