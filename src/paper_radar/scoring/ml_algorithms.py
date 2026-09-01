from __future__ import annotations

from datetime import date
from typing import Any

from paper_radar.models import Paper
from paper_radar.scoring.common import (
    add_matches,
    apply_rating,
    family_matches,
    recency_component,
    seed_component,
    venue_in,
    weighted_family_component,
)


def score_ml(paper: Paper, config: dict[str, Any], venues: dict[str, Any], today: date) -> Paper:
    families = config["families"]
    weights = config["weights"]
    requirements = config["requirements"]
    paper.matched_criteria = []
    paper.penalties = []
    paper.score_components = {}
    paper.excluded = False

    domain, domain_hits = weighted_family_component(
        paper, families["domain"], weights["domain_title"], weights["domain_abstract"]
    )
    method, method_hits = weighted_family_component(
        paper, families["method"], weights["method_title"], weights["method_abstract"]
    )
    formulation, formulation_hits = weighted_family_component(
        paper,
        families["formulation"],
        weights["formulation_title"],
        weights["formulation_abstract"],
    )
    negative_hits = family_matches(f"{paper.title} {paper.abstract}", families["negative"])
    add_matches(paper, domain_hits, method_hits, formulation_hits)
    paper.score_components.update(
        domain_relevance=round(domain, 3),
        actionable_method_signal=round(method, 3),
        conceptual_formulation_signal=round(formulation, 3),
    )
    understanding_synergy = (
        weights["understanding_synergy"]
        if "understanding" in method_hits and "observed-explained" in formulation_hits
        else 0.0
    )
    actionable_synergy = weights["actionable_synergy"] if domain >= 2.0 and method >= 1.8 else 0.0
    paper.score_components["model_understanding_synergy"] = understanding_synergy
    paper.score_components["actionable_design_synergy"] = actionable_synergy

    negative_penalty = weights["negative_penalty"] * len(negative_hits)
    paper.score_components["application_incremental_penalty"] = round(negative_penalty, 3)
    paper.penalties.extend(negative_hits)
    hard_negative = {"application-only", "systems", "llm-applied"}.intersection(negative_hits)
    if hard_negative and method < requirements["application_exclude_if_method_below"]:
        paper.excluded = True
        paper.penalties.append("task-specific/non-actionable")
    if "benchmark-only" in negative_hits and method == 0 and formulation == 0:
        paper.excluded = True
        paper.penalties.append("benchmark-only")

    is_theory = "theory" in domain_hits
    if (
        is_theory
        and "observed-explained" not in formulation_hits
        and method < requirements["pure_theory_positive_min"]
    ):
        paper.score_components["disconnected_theory_penalty"] = weights["negative_penalty"]
        paper.penalties.append("theory-without-model-design-connection")

    generic_categories = set(config["families"]["generic_required_categories"])
    if (
        generic_categories.intersection(paper.categories)
        and method < requirements["generic_category_min_method"]
    ):
        paper.score_components["task_specific_category_penalty"] = weights["negative_penalty"]
        paper.penalties.append("task-specific-category-without-generic-method-signal")

    venue_score = 0.0
    if venue_in(paper.venue, venues["top"]):
        venue_score = weights["venue_top"]
        paper.matched_criteria.append("top-venue")
    elif venue_in(paper.venue, venues["strong"]):
        venue_score = weights["venue_strong"]
        paper.matched_criteria.append("strong-venue")
    elif venue_in(paper.venue, venues.get("watch", [])) and (domain > 0 or method > 0):
        venue_score = weights["venue_watch"]
        paper.matched_criteria.append("watch-venue")
    elif (paper.venue or "").casefold() == "arxiv":
        venue_score = weights["arxiv_penalty"]
        paper.penalties.append("arXiv-strict-threshold")
    paper.score_components["venue_prior"] = venue_score
    paper.score_components["recency"] = recency_component(paper, today, weights["recency"], 14)
    seed = seed_component(paper.recommendation_rank, weights["seed_max"])
    paper.score_components["seed_bonus"] = seed
    if seed:
        paper.matched_criteria.append("seed-similarity")
    apply_rating(paper, config["thresholds"])
    return paper
