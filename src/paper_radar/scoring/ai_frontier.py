from __future__ import annotations

import math
from datetime import date
from typing import Any

from paper_radar.models import Paper
from paper_radar.scoring.common import (
    add_matches,
    apply_rating,
    family_matches,
    recency_component,
    venue_in,
)


def score_frontier(
    paper: Paper,
    config: dict[str, Any],
    today: date,
    venues: dict[str, list[str]] | None = None,
) -> Paper:
    families = config["families"]
    weights = config["weights"]
    ranking = config["ranking"]
    text = f"{paper.title} {paper.abstract}"
    paper.matched_criteria = []
    paper.penalties = []
    paper.score_components = {}
    paper.excluded = False

    core_hits = family_matches(text, families["core"])
    secondary_hits = family_matches(text, families["secondary"])
    breakthrough_hits = family_matches(text, families["breakthrough"])
    negative_hits = family_matches(text, families["negative"])
    add_matches(paper, core_hits, secondary_hits, breakthrough_hits)

    is_hf_candidate = paper.hf_rank is not None
    rank = paper.hf_rank or 999
    if is_hf_candidate and rank > ranking["core_max_rank"]:
        paper.excluded = True
        paper.penalties.append("outside-HF-candidate-pool")
    score_window = ranking.get("hf_rank_score_window", ranking["core_max_rank"])
    hf_score = (
        weights["hf_discovery_max"] * max(0.0, 1 - (rank - 1) / max(1, score_window - 1))
        if is_hf_candidate
        else 0.0
    )
    paper.score_components["hf_trending"] = round(hf_score, 3)
    if is_hf_candidate:
        paper.matched_criteria.append(f"HF Trending #{rank}")
    paper.score_components["core_topic"] = round(
        min(weights["core_topic_max"], weights["core_topic"] * len(core_hits)), 3
    )
    paper.score_components["secondary_topic"] = round(
        min(weights["secondary_topic_max"], weights["secondary_topic"] * len(secondary_hits)),
        3,
    )
    paper.score_components["qualitative_progress"] = round(
        weights["breakthrough"] * len(breakthrough_hits), 3
    )

    if not core_hits and not secondary_hits:
        paper.excluded = True
        paper.penalties.append("no-frontier-topic")
    if (
        is_hf_candidate
        and secondary_hits
        and not core_hits
        and rank > ranking["secondary_max_rank"]
    ):
        paper.excluded = True
        paper.penalties.append("secondary-topic-below-HF-rank-threshold")
    if negative_hits:
        paper.score_components["incremental_or_scope_penalty"] = weights["negative_penalty"] * len(
            negative_hits
        )
        paper.penalties.extend(negative_hits)
    if "pure-generation" in negative_hits and not {
        "world-model",
        "physical-ai",
        "vla",
    }.intersection(core_hits):
        paper.excluded = True
        paper.penalties.append("pure-image/video/3D-generation")

    age_days = (today - paper.publication_date).days if paper.publication_date else 0
    old = age_days > ranking["old_after_days"]
    legendary = (
        old
        and rank <= ranking["resurfaced_max_rank"]
        and (
            (paper.citation_count or 0) >= ranking["legendary_min_citations"]
            or (paper.influential_citation_count or 0)
            >= ranking["legendary_min_influential_citations"]
        )
    )
    if old and not legendary:
        paper.excluded = True
        paper.penalties.append("ordinary-old-paper")
    elif legendary:
        paper.matched_criteria.append("resurfaced/legendary")

    citation_value = (paper.citation_count or 0) + 5 * (paper.influential_citation_count or 0)
    paper.score_components["citation_signal"] = min(
        weights["citation_bonus_max"],
        math.log10(1 + citation_value) / 4 * weights["citation_bonus_max"],
    )
    venue_config = venues or {}
    venue_score = 0.0
    if venue_in(paper.venue, venue_config.get("top", [])):
        venue_score = weights["venue_top"]
        paper.matched_criteria.append("top-venue")
    elif venue_in(paper.venue, venue_config.get("strong", [])):
        venue_score = weights["venue_strong"]
        paper.matched_criteria.append("strong-venue")
    paper.score_components["venue_prior"] = venue_score
    paper.score_components["recency"] = recency_component(paper, today, weights["recency"], 30)
    apply_rating(paper, config["thresholds"])
    return paper
