from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from paper_radar.models import Paper, Rating


def contains(text: str, phrase: str) -> bool:
    pattern = rf"(?<!\w){re.escape(phrase.casefold())}(?!\w)"
    return re.search(pattern, text.casefold()) is not None


def family_matches(text: str, families: dict[str, list[str]]) -> list[str]:
    return [name for name, terms in families.items() if any(contains(text, term) for term in terms)]


def weighted_family_component(
    paper: Paper,
    families: dict[str, list[str]],
    title_weight: float,
    abstract_weight: float,
) -> tuple[float, list[str]]:
    title_hits = family_matches(paper.title, families)
    abstract_hits = family_matches(paper.abstract, families)
    criteria = list(dict.fromkeys(title_hits + abstract_hits))
    return len(title_hits) * title_weight + len(
        set(abstract_hits) - set(title_hits)
    ) * abstract_weight, criteria


def venue_in(venue: str | None, candidates: Iterable[str]) -> bool:
    def normalized(value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())

    current = normalized(venue or "")
    return any(current == normalized(candidate) for candidate in candidates)


def recency_component(paper: Paper, today: date, max_weight: float, window_days: int = 14) -> float:
    if not paper.publication_date:
        return max_weight * 0.25
    age = max(0, (today - paper.publication_date).days)
    return round(max_weight * max(0.0, 1 - age / max(window_days, 1)), 3)


def seed_component(rank: int | None, max_weight: float) -> float:
    if rank is None:
        return 0.0
    return round(max_weight / math.sqrt(max(1, rank)), 3)


def apply_rating(paper: Paper, thresholds: dict[str, float]) -> None:
    paper.score = round(sum(paper.score_components.values()), 3)
    if paper.excluded:
        paper.rating = Rating.EXCLUDED
    elif paper.score >= thresholds["must_read"]:
        paper.rating = Rating.MUST_READ
    elif paper.score >= thresholds["strong"]:
        paper.rating = Rating.STRONG
    elif paper.score >= thresholds["more_min_score"]:
        paper.rating = Rating.CANDIDATE
    else:
        paper.rating = Rating.BELOW


def add_matches(paper: Paper, *groups: list[str]) -> None:
    paper.matched_criteria = list(dict.fromkeys(item for group in groups for item in group))


def debug_score(paper: Paper) -> dict[str, Any]:
    return {
        "canonical_id": paper.canonical_id,
        "components": paper.score_components,
        "total": paper.score,
        "rating": paper.rating.value,
        "matched_criteria": paper.matched_criteria,
        "penalties": paper.penalties,
    }
