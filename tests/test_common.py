from __future__ import annotations

from paper_radar.dedup import deduplicate
from paper_radar.models import Rating
from paper_radar.pipeline import Pipeline
from paper_radar.scoring.bioinfo import score_bioinfo
from paper_radar.scoring.common import venue_in
from paper_radar.state import StateStore
from tests.conftest import make_paper


def test_dedup_doi_arxiv_and_title():
    doi = deduplicate(
        [
            make_paper(title="One", doi="10.1000/X"),
            make_paper(title="One copy", doi="https://doi.org/10.1000/x"),
        ]
    )
    arxiv = deduplicate(
        [
            make_paper(title="Two", arxiv_id="2401.00001v1"),
            make_paper(title="Two copy", arxiv_id="arXiv:2401.00001"),
        ]
    )
    title = deduplicate([make_paper(title="A Great Paper!"), make_paper(title="A great-paper")])
    assert len(doi) == len(arxiv) == len(title) == 1


def test_matched_criteria_and_state_persistence(config, today, tmp_path):
    paper = score_bioinfo(
        make_paper(
            title="RNA velocity with a probabilistic model",
            abstract=(
                "We introduce a new method and latent variable formulation "
                "for single-cell dynamics."
            ),
        ),
        config.category("bioinfo"),
        config.venues["bioinfo"],
        today,
    )
    assert {"rna-velocity", "formulation", "method-development"}.intersection(
        paper.matched_criteria
    )
    path = tmp_path / "state.json"
    state = StateStore(path)
    state.mark_sent(paper, "bioinfo")
    state.save()
    loaded = StateStore(path)
    assert loaded.was_sent(paper, "bioinfo")


def test_more_never_repeats_daily(config, tmp_path, monkeypatch):
    monkeypatch.setitem(config.common["state"], "path", str(tmp_path / "sent.json"))
    pipeline = Pipeline(config)
    daily = make_paper(title="Daily", canonical_id="doi:daily", score=9, rating=Rating.MUST_READ)
    next_paper = make_paper(title="Next", canonical_id="doi:next", score=5, rating=Rating.BELOW)
    pipeline.state.mark_sent(daily, "bioinfo")
    selected = pipeline.select_more("bioinfo", [daily, next_paper], 5)
    assert selected == [next_paper]


def test_venue_matching_does_not_use_substrings():
    assert venue_in("Science", ["Science"])
    assert not venue_in("iScience", ["Science"])
    assert not venue_in("Interdisciplinary sciences", ["Science"])
    assert not venue_in("Nature Communications", ["Nature"])
