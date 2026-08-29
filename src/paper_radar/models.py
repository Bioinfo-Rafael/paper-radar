from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class Rating(StrEnum):
    MUST_READ = "★★★★★ Must Read"
    STRONG = "★★★★☆ Strong"
    CANDIDATE = "★★★☆☆ Candidate"
    BELOW = "Below notification threshold"
    EXCLUDED = "Excluded"


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value.rstrip(".") or None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    value = re.sub(r"^(?:arxiv:|https?://arxiv\.org/(?:abs|pdf)/)", "", value)
    value = re.sub(r"v\d+$", "", value).removesuffix(".pdf")
    return value or None


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


@dataclass(slots=True)
class Paper:
    title: str
    paper_url: str
    source: str
    canonical_id: str | None = None
    abstract: str = ""
    publication_date: date | None = None
    year: int | None = None
    venue: str | None = None
    publication_type: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    biorxiv_doi: str | None = None
    semantic_scholar_id: str | None = None
    categories: list[str] = field(default_factory=list)
    citation_count: int | None = None
    influential_citation_count: int | None = None
    hf_rank: int | None = None
    recommendation_rank: int | None = None
    matched_criteria: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    score_components: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    importance_score: float | None = None
    freshness_bonus: float = 0.0
    retrieval_lane: str | None = None
    rating: Rating = Rating.BELOW
    excluded: bool = False
    preprint_doi: str | None = None
    published_doi: str | None = None

    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        self.biorxiv_doi = normalize_doi(self.biorxiv_doi)
        self.preprint_doi = normalize_doi(self.preprint_doi)
        self.published_doi = normalize_doi(self.published_doi)
        self.arxiv_id = normalize_arxiv_id(self.arxiv_id)
        self.year = self.year or (self.publication_date.year if self.publication_date else None)
        self.canonical_id = self.canonical_id or self.compute_canonical_id()

    def compute_canonical_id(self) -> str:
        if self.doi:
            return f"doi:{self.doi}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        if self.biorxiv_doi:
            return f"biorxiv:{self.biorxiv_doi}"
        if self.semantic_scholar_id:
            return f"s2:{self.semantic_scholar_id.lower()}"
        return f"title:{normalize_title(self.title)}"

    @property
    def publication_status(self) -> str:
        if self.published_doi or (self.doi and self.biorxiv_doi and self.doi != self.biorxiv_doi):
            return "published"
        if (
            self.arxiv_id
            or self.biorxiv_doi
            or (self.venue or "").casefold() in {"arxiv", "biorxiv"}
        ):
            return "preprint"
        return "published"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["publication_date"] = (
            self.publication_date.isoformat() if self.publication_date else None
        )
        data["rating"] = self.rating.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Paper:
        clean = dict(data)
        if clean.get("publication_date"):
            clean["publication_date"] = date.fromisoformat(clean["publication_date"])
        if clean.get("rating"):
            legacy_rating = "★★★☆☆ Below notification threshold"
            clean["rating"] = (
                Rating.BELOW if clean["rating"] == legacy_rating else Rating(clean["rating"])
            )
        return cls(**clean)
