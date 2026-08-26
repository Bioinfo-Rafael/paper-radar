from __future__ import annotations

from collections.abc import Iterable

from paper_radar.models import Paper, normalize_title


def identity_keys(paper: Paper) -> set[str]:
    keys = {
        paper.canonical_id or paper.compute_canonical_id(),
        f"title:{normalize_title(paper.title)}",
    }
    for prefix, value in (
        ("doi", paper.doi),
        ("arxiv", paper.arxiv_id),
        ("biorxiv", paper.biorxiv_doi),
        ("s2", paper.semantic_scholar_id),
    ):
        if value:
            keys.add(f"{prefix}:{value.casefold()}")
    return keys


def _richness(paper: Paper) -> tuple[int, int, int]:
    return (
        bool(paper.abstract) + bool(paper.venue) + bool(paper.publication_date),
        len(paper.abstract),
        paper.citation_count or 0,
    )


def merge_papers(primary: Paper, secondary: Paper) -> Paper:
    rich, other = (
        (primary, secondary) if _richness(primary) >= _richness(secondary) else (secondary, primary)
    )
    for name in (
        "abstract",
        "publication_date",
        "year",
        "venue",
        "publication_type",
        "doi",
        "arxiv_id",
        "biorxiv_doi",
        "semantic_scholar_id",
        "citation_count",
        "influential_citation_count",
        "hf_rank",
        "recommendation_rank",
        "preprint_doi",
        "published_doi",
    ):
        if getattr(rich, name) in (None, "", []):
            setattr(rich, name, getattr(other, name))
    rich.categories = sorted(set(rich.categories + other.categories))
    rich.source = "+".join(sorted(set(rich.source.split("+") + other.source.split("+"))))
    if secondary.recommendation_rank and (
        rich.recommendation_rank is None or secondary.recommendation_rank < rich.recommendation_rank
    ):
        rich.recommendation_rank = secondary.recommendation_rank
    rich.canonical_id = rich.compute_canonical_id()
    return rich


def deduplicate(papers: Iterable[Paper]) -> list[Paper]:
    result: list[Paper] = []
    key_to_index: dict[str, int] = {}
    for paper in papers:
        keys = identity_keys(paper)
        existing = next((key_to_index[key] for key in keys if key in key_to_index), None)
        if existing is None:
            index = len(result)
            result.append(paper)
        else:
            index = existing
            result[index] = merge_papers(result[index], paper)
        for key in identity_keys(result[index]):
            key_to_index[key] = index
    return result
