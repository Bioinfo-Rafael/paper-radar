from __future__ import annotations

from paper_radar.dedup import deduplicate
from tests.conftest import make_paper


def test_doi_duplicate_across_sources_merges_to_one():
    a = make_paper(title="A New Method", doi="10.1000/xyz", source="crossref_works")
    b = make_paper(title="A New Method", doi="10.1000/XYZ", source="openalex", abstract="Abstract.")
    result = deduplicate([a, b])
    assert len(result) == 1
    assert result[0].abstract == "Abstract."
    assert "crossref_works" in result[0].source
    assert "openalex" in result[0].source


def test_arxiv_and_crossref_same_paper_merges_to_one():
    arxiv_paper = make_paper(
        title="Flow Matching for Everything", arxiv_id="2608.12345", source="arxiv"
    )
    crossref_paper = make_paper(
        title="Flow Matching for Everything",
        doi="10.1000/abc",
        arxiv_id="2608.12345",
        source="crossref_works",
    )
    result = deduplicate([arxiv_paper, crossref_paper])
    assert len(result) == 1
    assert result[0].doi == "10.1000/abc"


def test_pubmed_id_dedup():
    a = make_paper(title="A Method For X", pubmed_id="12345", source="pubmed")
    b = make_paper(title="A Different Title Entirely", pubmed_id="12345", source="europepmc")
    result = deduplicate([a, b])
    assert len(result) == 1


def test_openalex_id_dedup():
    a = make_paper(title="A Method For Y", openalex_id="W123", source="openalex")
    b = make_paper(title="A rather different title", openalex_id="w123", source="openalex")
    result = deduplicate([a, b])
    assert len(result) == 1


def test_fuzzy_title_and_author_dedup_merges_near_duplicates():
    a = make_paper(
        title="A New Formulation for RNA Velocity",
        authors=["Jane Doe", "John Smith"],
        year=2026,
        source="pmlr",
    )
    b = make_paper(
        title="A New Formulation for RNA Velocity.",
        authors=["Jane Doe"],
        year=2026,
        source="neurips_proceedings",
        abstract="We introduce a new formulation.",
    )
    result = deduplicate([a, b])
    assert len(result) == 1
    assert result[0].abstract == "We introduce a new formulation."


def test_fuzzy_dedup_does_not_merge_genuinely_different_papers():
    a = make_paper(
        title="A New Formulation for RNA Velocity",
        authors=["Jane Doe"],
        year=2026,
    )
    b = make_paper(
        title="A New Formulation for Cell Fate Mapping",
        authors=["John Smith"],
        year=2026,
    )
    result = deduplicate([a, b])
    assert len(result) == 2


def test_fuzzy_dedup_respects_year_gap():
    a = make_paper(title="A Unified Framework for Diffusion Models", year=2020, authors=["A One"])
    b = make_paper(title="A Unified Framework for Diffusion Model", year=2026, authors=["A One"])
    result = deduplicate([a, b])
    assert len(result) == 2


def test_merge_prefers_richer_abstract_and_unions_authors():
    thin = make_paper(
        title="A Method",
        doi="10.1000/rich",
        abstract="",
        authors=["Jane Doe"],
        source="arxiv",
    )
    rich = make_paper(
        title="A Method",
        doi="10.1000/rich",
        abstract="A much richer abstract describing the method in detail.",
        authors=["John Smith"],
        source="crossref_works",
        citation_count=5,
    )
    result = deduplicate([thin, rich])
    assert len(result) == 1
    merged = result[0]
    assert merged.abstract == "A much richer abstract describing the method in detail."
    assert merged.citation_count == 5
    assert set(merged.authors) >= {"Jane Doe"}
