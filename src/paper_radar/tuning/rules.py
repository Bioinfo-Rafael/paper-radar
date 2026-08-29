from __future__ import annotations

from datetime import date
from typing import Any

from paper_radar.models import Paper
from paper_radar.scoring.common import apply_rating, contains, recency_component, venue_in

CATEGORIES = {"bioinfo", "ml", "frontier"}


def _text_matches(paper: Paper, keywords: list[str]) -> bool:
    text = f"{paper.title} {paper.abstract} {' '.join(paper.matched_criteria)}"
    return any(contains(text, keyword) for keyword in keywords if keyword.strip())


def _journal_matches(
    paper: Paper,
    rule: dict[str, Any],
    venue_config: dict[str, list[str]],
) -> bool:
    journal = rule.get("journal")
    if journal and venue_in(paper.venue, [journal]):
        return True
    group = rule.get("journal_group")
    if group == "top_journals":
        names = venue_config.get("tier_s", []) + venue_config.get("tier_a", [])
        names += venue_config.get("top", [])
        return venue_in(paper.venue, names)
    return bool(group and venue_in(paper.venue, venue_config.get(group, [])))


def _signal_present(paper: Paper, target: str) -> bool:
    terms = {
        "method": ("method", "actionable", "algorithm", "architecture"),
        "formulation": ("formulation", "conceptual", "objective", "process"),
        "phenomenon": ("understanding", "phenomenon", "qualitative", "emergence"),
        "benchmark": ("benchmark", "evaluation", "failure"),
        "application_only": ("application", "task-specific", "incremental"),
        "journal": ("venue",),
        "freshness": ("recency",),
    }[target]
    evidence = " ".join(
        [*paper.score_components.keys(), *paper.matched_criteria, *paper.penalties]
    ).casefold()
    return any(term in evidence for term in terms)


def apply_tuning(
    paper: Paper,
    category: str,
    tuning: dict[str, Any],
    base_thresholds: dict[str, float],
    venue_config: dict[str, list[str]],
    today: date,
) -> Paper:
    """Apply validated user tuning after the deterministic base scorer."""
    for rule in tuning.get("concepts", []):
        if rule["channel"] != category or not _text_matches(paper, rule["keywords"]):
            continue
        value = abs(float(rule["weight"]))
        if rule["polarity"] == "negative":
            value = -value
            paper.penalties.append(f"tuned-negative:{rule['concept']}")
        else:
            paper.matched_criteria.append(f"tuned:{rule['concept']}")
        paper.score_components[f"tuned_concept:{rule['concept']}"] = value

    for rule in tuning.get("signal_adjustments", []):
        if rule["channel"] == category and _signal_present(paper, rule["target"]):
            paper.score_components[f"tuned_signal:{rule['target']}"] = float(rule["amount"])

    for rule in tuning.get("journal_priorities", []):
        if rule["channel"] == category and _journal_matches(paper, rule, venue_config):
            paper.score_components["tuned_journal_priority"] = float(rule["weight"])
            paper.matched_criteria.append("tuned-journal-priority")

    freshness = next(
        (rule for rule in tuning.get("freshness", []) if rule["channel"] == category), None
    )
    if freshness:
        paper.score_components["recency"] = recency_component(
            paper, today, float(freshness["weight"]), int(freshness["days"])
        )

    for rule in tuning.get("backfill", []):
        if rule["channel"] == category and _journal_matches(paper, rule, venue_config):
            age = (today - paper.publication_date).days if paper.publication_date else 0
            if age <= int(rule["days"]):
                paper.score_components["tuned_backfill"] = float(rule["priority"])
                paper.matched_criteria.append("tuned-backfill")

    for rule in tuning.get("routing", []):
        if not _text_matches(paper, rule["keywords"]):
            continue
        preferred = rule["preferred_channel"]
        if category == preferred:
            paper.score_components[f"tuned_route:{rule['concept']}"] = 2.0
            paper.matched_criteria.append(f"route:{preferred}")
        else:
            paper.score_components[f"tuned_route:{rule['concept']}"] = -6.0
            paper.penalties.append(f"route-to:{preferred}")

    for rule in tuning.get("type_preferences", []):
        if rule["channel"] == category and _text_matches(paper, [rule["paper_type"]]):
            paper.score_components[f"tuned_type:{rule['paper_type']}"] = float(rule["weight"])

    thresholds = dict(base_thresholds)
    override = next(
        (rule for rule in tuning.get("thresholds", []) if rule["channel"] == category), None
    )
    if override:
        thresholds["more_min_score"] = float(override["value"])
    apply_rating(paper, thresholds)
    return paper


def tuning_lookback_days(tuning: dict[str, Any], category: str, base_days: int) -> int:
    days = [
        int(rule["days"]) for rule in tuning.get("backfill", []) if rule.get("channel") == category
    ]
    return max([base_days, *days])
