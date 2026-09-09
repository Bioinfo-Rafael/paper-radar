from __future__ import annotations

import re
from dataclasses import dataclass

from paper_radar.models import Paper, normalize_arxiv_id, normalize_doi, normalize_title

_DOI_URL_RE = re.compile(r"doi\.org/(.+)$", re.IGNORECASE)


def extract_doi_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _DOI_URL_RE.search(url)
    return normalize_doi(match.group(1)) if match else None


def extract_arxiv_id_from_url(url: str | None) -> str | None:
    if not url or "arxiv.org" not in url.lower():
        return None
    return normalize_arxiv_id(url)


def synthesize_canonical_id(url: str | None, title: str) -> str:
    """Best-effort canonical id from Discord embed fields alone.

    Mirrors ``Paper.compute_canonical_id``'s priority (doi > arxiv > title) so
    a paper identified only from a Discord message lines up with the same
    paper's canonical id once/if it is independently re-derived elsewhere.
    """
    doi = extract_doi_from_url(url)
    if doi:
        return f"doi:{doi}"
    arxiv_id = extract_arxiv_id_from_url(url)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return f"title:{normalize_title(title)}"


@dataclass(frozen=True, slots=True)
class MatchedPaper:
    canonical_id: str
    title: str
    paper_url: str
    abstract: str
    category: str | None
    publication_date: str | None
    venue: str | None
    score: float | None
    rating: str | None
    doi: str | None
    arxiv_id: str | None
    semantic_scholar_id: str | None
    matched_locally: bool

    @classmethod
    def from_paper(cls, paper: Paper, category: str) -> MatchedPaper:
        return cls(
            canonical_id=paper.canonical_id or paper.compute_canonical_id(),
            title=paper.title,
            paper_url=paper.paper_url,
            abstract=paper.abstract or "",
            category=category,
            publication_date=paper.publication_date.isoformat()
            if paper.publication_date
            else None,
            venue=paper.venue,
            score=paper.score,
            rating=paper.rating.value if paper.rating else None,
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
            semantic_scholar_id=paper.semantic_scholar_id,
            matched_locally=True,
        )

    @classmethod
    def unmatched(cls, url: str, title: str) -> MatchedPaper:
        return cls(
            canonical_id=synthesize_canonical_id(url, title),
            title=title,
            paper_url=url,
            abstract="",
            category=None,
            publication_date=None,
            venue=None,
            score=None,
            rating=None,
            doi=extract_doi_from_url(url),
            arxiv_id=extract_arxiv_id_from_url(url),
            semantic_scholar_id=None,
            matched_locally=False,
        )


def match_candidate(
    embed_title: str,
    embed_url: str,
    candidates_by_category: dict[str, list[Paper]],
) -> MatchedPaper:
    """Identify a Discord paper embed against the existing candidate cache.

    Match priority, per spec: paper_url first, then canonical_id, and only
    then a normalized-title fallback. Read-only: never mutates the cache.
    """
    normalized_target_title = normalize_title(embed_title)
    synthesized_id = synthesize_canonical_id(embed_url, embed_title)
    normalized_url = (embed_url or "").strip()

    if normalized_url:
        for category, papers in candidates_by_category.items():
            for paper in papers:
                if paper.paper_url and paper.paper_url.strip() == normalized_url:
                    return MatchedPaper.from_paper(paper, category)

    for category, papers in candidates_by_category.items():
        for paper in papers:
            candidate_id = paper.canonical_id or paper.compute_canonical_id()
            if candidate_id == synthesized_id:
                return MatchedPaper.from_paper(paper, category)

    for category, papers in candidates_by_category.items():
        for paper in papers:
            if normalize_title(paper.title) == normalized_target_title:
                return MatchedPaper.from_paper(paper, category)

    return MatchedPaper.unmatched(embed_url, embed_title)
