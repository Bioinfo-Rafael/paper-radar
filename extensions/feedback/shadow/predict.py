from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from extensions.feedback.config import CATEGORIES
from extensions.feedback.shadow.aggregation import (
    DEFAULT_AGGREGATIONS,
    WeightedReaction,
    build_profile,
    score_profile,
)
from extensions.feedback.shadow.registry import available_models, build_registry
from extensions.feedback.state_store import FeedbackStateStore
from paper_radar.config import find_project_root
from paper_radar.models import Paper
from paper_radar.state import load_candidate_cache

LOGGER = logging.getLogger(__name__)

MIN_REACTIONS_FOR_INFERENCE = 20

# Must line up with extensions/feedback/reactions.yaml: this is a fallback
# only used if a raw event predates a config change (weight itself always
# comes from the config that produced the event, recorded on the event as
# reaction_strength — this table just orders/weights the three classes for
# profile-building; keep 👍 < ❤️ < ❤️‍🔥).
STRENGTH_WEIGHTS = {"weak": 1.0, "medium": 2.0, "strong": 3.0}


@dataclass(frozen=True, slots=True)
class EnrichedReaction:
    canonical_id: str
    title: str
    abstract: str
    reaction_strength: str
    detected_at: str


def _text_for(title: str, abstract: str) -> str:
    return f"{title}\n\n{abstract}".strip()


def load_enriched_reactions(state: FeedbackStateStore) -> list[EnrichedReaction]:
    reactions: list[EnrichedReaction] = []
    for raw in state.read_raw_events():
        abstract = raw.get("abstract_inline") or state.get_enriched_abstract(
            raw["canonical_id"]
        )
        if not abstract:
            continue
        reactions.append(
            EnrichedReaction(
                canonical_id=raw["canonical_id"],
                title=raw["title"],
                abstract=abstract,
                reaction_strength=raw["reaction_strength"],
                detected_at=raw["detected_at"],
            )
        )
    return reactions


def _age_days(detected_at: str, now: datetime) -> float:
    try:
        detected = datetime.fromisoformat(detected_at)
    except ValueError:
        return 0.0
    if detected.tzinfo is None:
        detected = detected.replace(tzinfo=UTC)
    return max(0.0, (now - detected).total_seconds() / 86400)


def _input_data_hash(reactions: list[EnrichedReaction]) -> str:
    fingerprint = sorted(
        f"{r.canonical_id}:{r.detected_at}:{r.reaction_strength}" for r in reactions
    )
    return hashlib.sha256(json.dumps(fingerprint).encode("utf-8")).hexdigest()[:16]


def load_scoreable_candidates(root: Path) -> list[Paper]:
    candidates_path = root / "state" / "candidates.json"
    papers: list[Paper] = []
    for category in CATEGORIES:
        papers.extend(
            paper
            for paper in load_candidate_cache(candidates_path, category)
            if paper.abstract
        )
    return papers


def compute_predictions(
    reactions: list[EnrichedReaction],
    candidates: list[Paper],
    now: datetime,
    *,
    registry: dict[str, Any] | None = None,
    aggregations=DEFAULT_AGGREGATIONS,
    min_reactions: int = MIN_REACTIONS_FOR_INFERENCE,
) -> list[dict[str, Any]]:
    """Pure function: never touches ``paper.score``/``paper.rating`` and
    never writes anywhere. Returns prediction rows only; production
    ranking/selection is not reachable from here.
    """
    if len(reactions) < min_reactions:
        return []
    candidates = [paper for paper in candidates if paper.abstract]
    if not candidates:
        return []
    input_hash = _input_data_hash(reactions)
    models = available_models(registry if registry is not None else build_registry())
    rows: list[dict[str, Any]] = []
    reaction_texts = [_text_for(r.title, r.abstract) for r in reactions]
    candidate_texts = [_text_for(p.title, p.abstract) for p in candidates]
    for model in models.values():
        model.fit(reaction_texts + candidate_texts)
        weighted_vectors = [
            WeightedReaction(
                vector=model.embed(text),
                weight=STRENGTH_WEIGHTS.get(reaction.reaction_strength, 1.0),
                reaction_type=reaction.reaction_strength,
                age_days=_age_days(reaction.detected_at, now),
            )
            for text, reaction in zip(reaction_texts, reactions, strict=True)
        ]
        for agg_config in aggregations:
            profile = build_profile(agg_config, weighted_vectors)
            if profile is None:
                continue
            for paper in candidates:
                paper_vector = model.embed(_text_for(paper.title, paper.abstract))
                score = score_profile(profile, paper_vector, model)
                rows.append(
                    {
                        "canonical_id": paper.canonical_id,
                        "model_name": model.info.model_name,
                        "model_version": model.info.model_version,
                        "profile_version": agg_config.version,
                        "aggregation_method": agg_config.name,
                        "interest_score": score,
                        "computed_at": now.isoformat(),
                        "input_data_hash": input_hash,
                    }
                )
    return rows


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    parser = argparse.ArgumentParser(prog="feedback-shadow-predict")
    parser.add_argument("--state-dir", default=os.getenv("FEEDBACK_STATE_DIR", "feedback-state"))
    args = parser.parse_args(argv)

    state = FeedbackStateStore(Path(args.state_dir))
    reactions = load_enriched_reactions(state)
    if len(reactions) < MIN_REACTIONS_FOR_INFERENCE:
        LOGGER.info(
            "insufficient feedback data: %d enriched reaction(s), need >= %d",
            len(reactions),
            MIN_REACTIONS_FOR_INFERENCE,
        )
        return 0
    try:
        root = find_project_root()
        candidates = load_scoreable_candidates(root)
        rows = compute_predictions(reactions, candidates, datetime.now(UTC))
    except Exception:
        LOGGER.exception("Shadow prediction failed for this run; nothing written")
        return 0
    state.append_predictions(rows)
    LOGGER.info(
        "Shadow prediction summary: %d reaction(s), %d candidate(s), %d row(s) written",
        len(reactions),
        len(candidates),
        len(rows),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
