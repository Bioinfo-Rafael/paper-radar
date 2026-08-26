from __future__ import annotations

import math
from datetime import date
from typing import Any

from paper_radar.models import Paper
from paper_radar.scoring.common import add_matches, apply_rating, family_matches, recency_component


def score_frontier(paper: Paper, config: dict[str, Any], today: date) -> Paper:
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

    rank = paper.hf_rank or 999
    if rank > ranking["core_max_rank"]:
        paper.excluded = True
        paper.penalties.append("outside-HF-candidate-pool")
    score_window = ranking.get("hf_rank_score_window", ranking["core_max_rank"])
    hf_score = weights["hf_rank_max"] * max(0.0, 1 - (rank - 1) / max(1, score_window - 1))
    paper.score_components["hf_trending"] = round(hf_score, 3)
    paper.matched_criteria.append(f"HF Trending #{rank}")
    paper.score_components["core_topic"] = round(weights["core_topic"] * len(core_hits), 3)
    paper.score_components["secondary_topic"] = round(
        weights["secondary_topic"] * len(secondary_hits), 3
    )
    paper.score_components["qualitative_progress"] = round(
        weights["breakthrough"] * len(breakthrough_hits), 3
    )

    if not core_hits and not secondary_hits:
        paper.excluded = True
        paper.penalties.append("no-frontier-topic")
    if secondary_hits and not core_hits and rank > ranking["secondary_max_rank"]:
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
    paper.score_components["recency"] = recency_component(paper, today, weights["recency"], 30)
    apply_rating(paper, config["thresholds"])
    return paper
