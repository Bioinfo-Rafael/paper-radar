from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher

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
        ("pubmed", paper.pubmed_id),
        ("openalex", paper.openalex_id),
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
        "pubmed_id",
        "openalex_id",
        "citation_count",
        "influential_citation_count",
        "hf_rank",
        "recommendation_rank",
        "preprint_doi",
        "published_doi",
    ):
        if getattr(rich, name) in (None, "", []):
            setattr(rich, name, getattr(other, name))
    rich.authors = list(dict.fromkeys(rich.authors + other.authors))
    rich.categories = sorted(set(rich.categories + other.categories))
    rich.source = "+".join(sorted(set(rich.source.split("+") + other.source.split("+"))))
    if secondary.recommendation_rank and (
        rich.recommendation_rank is None or secondary.recommendation_rank < rich.recommendation_rank
    ):
        rich.recommendation_rank = secondary.recommendation_rank
    rich.canonical_id = rich.compute_canonical_id()
    return rich


def _normalized_authors(paper: Paper) -> set[str]:
    return {normalize_title(author) for author in paper.authors if author}


def _fuzzy_match(a: Paper, b: Paper) -> bool:
    if a.year and b.year and abs(a.year - b.year) > 1:
        return False
    title_a, title_b = normalize_title(a.title), normalize_title(b.title)
    if not title_a or not title_b:
        return False
    # A quick length-ratio guard avoids running SequenceMatcher (comparatively
    # expensive) on pairs that cannot plausibly reach the similarity bar.
    shorter, longer = sorted((len(title_a), len(title_b)))
    if shorter / longer < 0.85:
        return False
    ratio = SequenceMatcher(None, title_a, title_b).ratio()
    # Title-only near-duplicates must be almost identical (punctuation/case
    # variants) -- a mid-range ratio alone is not enough, since two distinct
    # papers can share a long common template (e.g. differing only by a
    # model size or version number) and still score above 0.9.
    if ratio >= 0.97:
        return True
    if ratio >= 0.90 and _normalized_authors(a) & _normalized_authors(b):
        return True
    return False


def _block_key(paper: Paper) -> str:
    # Near-duplicate titles differ by punctuation/case or a short suffix, so
    # they almost always share their first few normalized characters. This
    # blocking keeps the fuzzy pass close to linear on large candidate pools
    # instead of comparing every paper against every other one.
    return normalize_title(paper.title)[:8]


def _fuzzy_merge(result: list[Paper]) -> list[Paper]:
    merged: list[Paper] = []
    buckets: dict[str, list[int]] = {}
    for paper in result:
        key = _block_key(paper)
        match_index = next(
            (index for index in buckets.get(key, ()) if _fuzzy_match(merged[index], paper)),
            None,
        )
        if match_index is None:
            buckets.setdefault(key, []).append(len(merged))
            merged.append(paper)
        else:
            merged[match_index] = merge_papers(merged[match_index], paper)
    return merged


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
    return _fuzzy_merge(result)
