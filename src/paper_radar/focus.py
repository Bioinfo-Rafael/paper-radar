from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from paper_radar.models import Paper
from paper_radar.scoring.common import apply_rating

STOP_WORDS = {"a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "with"}


def normalize_focus(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


@dataclass(frozen=True, slots=True)
class FocusSpec:
    raw: str
    families: tuple[str, ...]
    aliases: tuple[str, ...]

    @property
    def queries(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.raw, *self.aliases)))


def resolve_focus(raw: str | None, config: dict[str, Any]) -> FocusSpec | None:
    if not raw or not raw.strip():
        return None
    clean = " ".join(raw.split())[:200]
    normalized = normalize_focus(clean)
    matched: list[tuple[str, list[str]]] = []
    for group in config.get("families", {}).values():
        if not isinstance(group, dict):
            continue
        for family, aliases in group.items():
            candidates = [family, *aliases]
            normalized_candidates = [normalize_focus(value) for value in candidates]
            if any(
                candidate == normalized
                or (candidate and f" {candidate} " in f" {normalized} ")
                for candidate in normalized_candidates
            ):
                matched.append((family, list(aliases)))
    if not matched:
        return FocusSpec(clean, (), (clean,))
    families = tuple(dict.fromkeys(family for family, _ in matched))
    aliases = tuple(dict.fromkeys(alias for _, values in matched for alias in values))
    return FocusSpec(clean, families, aliases)


def _token_coverage(phrase: str, text: str) -> float:
    wanted = {
        token
        for token in normalize_focus(phrase).split()
        if token not in STOP_WORDS and len(token) > 1
    }
    if not wanted:
        return 0.0
    present = set(normalize_focus(text).split())
    return len(wanted & present) / len(wanted)


def apply_focus_bonus(
    paper: Paper,
    focus: FocusSpec | None,
    thresholds: dict[str, float],
    settings: dict[str, Any],
) -> Paper:
    if not focus:
        return paper
    title = normalize_focus(paper.title)
    abstract = normalize_focus(paper.abstract)
    phrases = focus.aliases or (focus.raw,)
    title_match = any(normalize_focus(phrase) in title for phrase in phrases)
    abstract_match = any(normalize_focus(phrase) in abstract for phrase in phrases)
    if title_match:
        bonus = float(settings["title_bonus"])
    elif abstract_match:
        bonus = float(settings["abstract_bonus"])
    elif focus.families:
        bonus = 0.0
    else:
        coverage = max(
            _token_coverage(focus.raw, paper.title),
            _token_coverage(focus.raw, paper.abstract) * 0.75,
        )
        bonus = float(settings["title_bonus"]) * coverage if coverage >= 0.5 else 0.0
    paper.score_components["focus_bonus"] = min(float(settings["max_bonus"]), bonus)
    if bonus and focus.families:
        paper.matched_criteria.extend(
            family for family in focus.families if family not in paper.matched_criteria
        )
    apply_rating(paper, thresholds)
    return paper
