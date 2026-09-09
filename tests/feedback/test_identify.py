from __future__ import annotations

from datetime import date

from extensions.feedback.identify import match_candidate, synthesize_canonical_id
from paper_radar.models import Rating
from tests.conftest import make_paper


def test_match_by_exact_paper_url_has_highest_priority():
    candidate = make_paper(
        title="A totally different title in the cache",
        paper_url="https://arxiv.org/abs/2609.02644",
        abstract="cached abstract",
        canonical_id="arxiv:2609.02644",
    )
    matched = match_candidate(
        "Whatever the embed title says",
        "https://arxiv.org/abs/2609.02644",
        {"ml": [candidate]},
    )
    assert matched.matched_locally is True
    assert matched.abstract == "cached abstract"
    assert matched.canonical_id == "arxiv:2609.02644"


def test_match_by_synthesized_canonical_id_when_url_differs():
    candidate = make_paper(
        title="Some paper",
        paper_url="https://arxiv.org/abs/2609.02644v2",
        abstract="cached abstract",
        canonical_id="arxiv:2609.02644",
        arxiv_id="2609.02644",
    )
    matched = match_candidate(
        "Some paper", "https://arxiv.org/abs/2609.02644", {"ml": [candidate]}
    )
    assert matched.matched_locally is True
    assert matched.abstract == "cached abstract"


def test_match_by_normalized_title_is_the_last_resort_fallback():
    candidate = make_paper(
        title="A Method For Doing Things!",
        paper_url="https://example.test/original-source",
        abstract="cached abstract",
    )
    matched = match_candidate(
        "a method for doing things",
        "https://example.test/completely-unrelated-mirror",
        {"bioinfo": [candidate]},
    )
    assert matched.matched_locally is True
    assert matched.abstract == "cached abstract"


def test_unmatched_paper_still_synthesizes_a_canonical_id_and_identifiers():
    empty_cache: dict[str, list] = {"bioinfo": [], "ml": [], "frontier": []}
    matched = match_candidate(
        "An unseen paper", "https://arxiv.org/abs/2601.12345", empty_cache
    )
    assert matched.matched_locally is False
    assert matched.abstract == ""
    assert matched.canonical_id == "arxiv:2601.12345"
    assert matched.arxiv_id == "2601.12345"


def test_unmatched_paper_with_no_recoverable_identifier_falls_back_to_title():
    empty_cache: dict[str, list] = {"bioinfo": [], "ml": [], "frontier": []}
    matched = match_candidate(
        "An unseen paper", "https://example.test/blog/some-post", empty_cache
    )
    assert matched.matched_locally is False
    assert matched.doi is None
    assert matched.arxiv_id is None
    assert matched.canonical_id == synthesize_canonical_id(
        "https://example.test/blog/some-post", "An unseen paper"
    )
    assert matched.canonical_id.startswith("title:")


def test_synthesize_canonical_id_extracts_doi_from_doi_org_url():
    assert synthesize_canonical_id(
        "https://doi.org/10.1038/s41586-026-10644-y", "Some title"
    ) == "doi:10.1038/s41586-026-10644-y"


def test_original_score_and_rating_are_carried_when_matched():
    candidate = make_paper(
        title="Rated paper",
        paper_url="https://example.test/rated",
        score=8.2,
        publication_date=date(2026, 8, 1),
    )

    candidate.rating = Rating.MUST_READ
    matched = match_candidate("Rated paper", "https://example.test/rated", {"bioinfo": [candidate]})
    assert matched.score == 8.2
    assert matched.rating == "★★★★★ Must Read"
