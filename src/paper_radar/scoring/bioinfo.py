from __future__ import annotations

from datetime import date
from typing import Any

from paper_radar.models import Paper, Rating
from paper_radar.scoring.common import (
    add_matches,
    apply_rating,
    family_matches,
    recency_component,
    seed_component,
    venue_in,
    weighted_family_component,
)


def score_bioinfo(
    paper: Paper,
    config: dict[str, Any],
    venues: dict[str, Any],
    today: date,
) -> Paper:
    families = config["families"]
    weights = config["weights"]
    requirements = config["requirements"]
    paper.matched_criteria = []
    paper.penalties = []
    paper.score_components = {}
    paper.excluded = False

    publication_text = f"{paper.publication_type or ''} {paper.title}"
    review_terms = families["reviews"]
    if any(term.casefold() in publication_text.casefold() for term in review_terms):
        paper.excluded = True
        paper.penalties.append("review/publication-type")

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
    scientific_value, scientific_value_hits = weighted_family_component(
        paper,
        families["scientific_value"],
        weights["scientific_value_title"],
        weights["scientific_value_abstract"],
    )
    application_hits = family_matches(
        f"{paper.title} {paper.abstract}", families["application_only"]
    )
    low_hits = family_matches(f"{paper.title} {paper.abstract}", families["low_priority"])
    add_matches(paper, domain_hits, method_hits, formulation_hits, scientific_value_hits)

    paper.score_components.update(
        domain_relevance=round(domain, 3),
        method_signal=round(method, 3),
        formulation_signal=round(formulation, 3),
        scientific_value=round(scientific_value, 3),
    )
    application_penalty = 0.0
    if application_hits:
        application_penalty = weights["application_penalty"]
        paper.penalties.extend(application_hits)
        if method < requirements["application_exclude_if_method_below"]:
            paper.excluded = True
            paper.penalties.append("application-only-without-method-development")
    paper.score_components["application_penalty"] = application_penalty

    low_penalty = weights["low_priority_penalty"] * len(low_hits)
    if low_hits:
        paper.penalties.extend(low_hits)
    paper.score_components["low_priority_penalty"] = round(low_penalty, 3)

    venue_score = 0.0
    venue_criteria: list[str] = []
    if venue_in(paper.venue, venues["tier_s"]):
        venue_score = weights["venue_s"]
        venue_criteria.append("top-venue")
    elif venue_in(paper.venue, venues["tier_a"]):
        venue_score = weights["venue_a"]
        venue_criteria.append("strong-venue")
    elif venue_in(paper.venue, venues["specialist"]):
        venue_score = weights["venue_specialist"]
        venue_criteria.append("specialist-venue")
    elif venue_in(paper.venue, venues["preprint"]):
        venue_score = weights["venue_preprint"]
        venue_criteria.append("preprint")
    paper.score_components["venue_prior"] = venue_score
    paper.matched_criteria.extend(venue_criteria)

    is_spatial = "spatial" in domain_hits
    if is_spatial:
        if method < requirements["spatial_min_method"]:
            paper.excluded = True
            paper.penalties.append("spatial-application-without-method-development")
        if not venue_in(paper.venue, venues["spatial_high"]):
            paper.score_components["spatial_venue_adjustment"] = weights[
                "spatial_low_venue_penalty"
            ]
            paper.penalties.append("spatial-low-venue-prior")

    foundation_restricted = "foundation-model" in domain_hits and not venue_in(
        paper.venue, venues["foundation_high"]
    )
    if foundation_restricted:
        paper.score_components["foundation_venue_adjustment"] = weights[
            "foundation_low_venue_penalty"
        ]
        paper.penalties.append("foundation-model-low-venue-prior")

    recency = recency_component(paper, today, weights["recency"], 14)
    seed = seed_component(paper.recommendation_rank, weights["seed_max"])
    paper.score_components["recency"] = recency
    paper.score_components["seed_bonus"] = seed
    if seed:
        paper.matched_criteria.append("seed-similarity")
    if paper.published_doi and paper.preprint_doi:
        paper.matched_criteria.append("bioRxiv→formal-publication")

    apply_rating(paper, config["thresholds"])
    if (
        not paper.excluded
        and foundation_restricted
        and formulation < requirements["foundation_preprint_strong_min_formulation"]
        and (paper.importance_score or 0) >= config["thresholds"]["strong"]
    ):
        paper.importance_score = config["thresholds"]["strong"] - 0.001
        paper.score = paper.importance_score + paper.freshness_bonus
        paper.rating = (
            Rating.CANDIDATE
            if paper.importance_score >= config["thresholds"]["more_min_score"]
            else Rating.BELOW
        )
    return paper
