from __future__ import annotations

from datetime import UTC, datetime

from extensions.feedback.shadow.aggregation import (
    AggregationConfig,
    WeightedReaction,
    build_profile,
    cosine,
    score_profile,
)
from extensions.feedback.shadow.interfaces import ChallengerInfo, ChallengerModel
from extensions.feedback.shadow.lexical_tfidf import TFIDFChallenger
from extensions.feedback.shadow.predict import (
    MIN_REACTIONS_FOR_INFERENCE,
    EnrichedReaction,
    compute_predictions,
)
from extensions.feedback.shadow.registry import available_models, build_registry
from tests.conftest import make_paper

NOW = datetime(2026, 9, 9, tzinfo=UTC)


class _UnavailableChallenger(ChallengerModel):
    info = ChallengerInfo(model_name="unavailable-model", model_version="0.0")

    def is_available(self) -> bool:
        return False


class _FakeDenseChallenger(ChallengerModel):
    """Deterministic fake embedding: bag-of-words one-hot-ish dense vector
    over a tiny fixed vocabulary, so tests don't depend on any ML library.
    """

    info = ChallengerInfo(model_name="fake-dense", model_version="test")
    vector_kind = "dense"
    VOCAB = ["cats", "dogs", "graphs", "networks", "cells", "genes"]

    def is_available(self) -> bool:
        return True

    def embed(self, text: str):
        lowered = (text or "").lower()
        return [float(lowered.count(word)) for word in self.VOCAB]

    def similarity(self, a, b) -> float:
        return cosine(a, b)


def test_registry_lists_tfidf_as_always_available():
    registry = build_registry()
    available = available_models(registry)
    assert "tfidf-lexical" in available


def test_registry_never_hard_codes_a_single_winner_and_skips_unavailable_models():
    registry = {"tfidf-lexical": TFIDFChallenger(), "nope": _UnavailableChallenger()}
    available = available_models(registry)
    assert set(available) == {"tfidf-lexical"}


def test_tfidf_similarity_ranks_related_text_higher_than_unrelated():
    model = TFIDFChallenger()
    corpus = [
        "single cell RNA velocity gene regulatory network",
        "graph neural networks for molecule generation",
        "a robot learns to walk using reinforcement learning",
    ]
    model.fit(corpus)
    query = model.embed("single cell gene regulatory network inference")
    related = model.embed(corpus[0])
    unrelated = model.embed(corpus[2])
    assert model.similarity(query, related) > model.similarity(query, unrelated)


def test_weighted_centroid_and_per_reaction_type_produce_different_profiles():
    reactions = [
        WeightedReaction(
            vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0], weight=1.0, reaction_type="weak", age_days=0
        ),
        WeightedReaction(
            vector=[0.0, 0.0, 0.0, 0.0, 1.0, 1.0], weight=3.0, reaction_type="strong", age_days=0
        ),
    ]
    centroid_profile = build_profile(
        AggregationConfig(name="centroid", version="v1", method="centroid"), reactions
    )
    per_type_profile = build_profile(
        AggregationConfig(name="per_reaction_type", version="v1", method="per_reaction_type"),
        reactions,
    )
    assert len(centroid_profile) == 1
    assert len(per_type_profile) == 2
    assert {label for label, _, _ in per_type_profile} == {"weak", "strong"}


def test_clustering_is_unsupported_for_sparse_vectors():
    reactions = [
        WeightedReaction(vector={"a": 1.0}, weight=1.0, reaction_type="weak", age_days=0),
        WeightedReaction(vector={"b": 1.0}, weight=1.0, reaction_type="weak", age_days=0),
    ]
    profile = build_profile(
        AggregationConfig(name="clusters_k2", version="v1", method="clusters", k_clusters=2),
        reactions,
    )
    assert profile is None


def test_recency_half_life_down_weights_older_reactions():
    fresh = WeightedReaction(
        vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0], weight=1.0, reaction_type="weak", age_days=0
    )
    stale = WeightedReaction(
        vector=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0], weight=1.0, reaction_type="weak", age_days=365
    )
    profile = build_profile(
        AggregationConfig(
            name="centroid_recency", version="v1", method="centroid", half_life_days=30.0
        ),
        [fresh, stale],
    )
    _, vector, _ = profile[0]
    assert vector[0] > vector[1]


def test_insufficient_feedback_data_yields_no_predictions():
    reactions = [
        EnrichedReaction(
            canonical_id=f"arxiv:{i}",
            title=f"Paper {i}",
            abstract="single cell gene regulatory network",
            reaction_strength="weak",
            detected_at=NOW.isoformat(),
        )
        for i in range(MIN_REACTIONS_FOR_INFERENCE - 1)
    ]
    candidates = [make_paper(title="Candidate", abstract="single cell dynamics")]
    rows = compute_predictions(
        reactions, candidates, NOW, registry={"fake-dense": _FakeDenseChallenger()}
    )
    assert rows == []


def test_predictions_never_mutate_the_scored_papers():
    reactions = [
        EnrichedReaction(
            canonical_id=f"arxiv:{i}",
            title=f"Paper about cats {i}",
            abstract="cats and dogs",
            reaction_strength="strong",
            detected_at=NOW.isoformat(),
        )
        for i in range(MIN_REACTIONS_FOR_INFERENCE)
    ]
    candidate = make_paper(title="Graphs and networks", abstract="graphs and networks paper")
    candidate.score = 4.2
    original_score = candidate.score
    original_rating = candidate.rating

    rows = compute_predictions(
        reactions, [candidate], NOW, registry={"fake-dense": _FakeDenseChallenger()}
    )

    assert candidate.score == original_score
    assert candidate.rating == original_rating
    assert rows
    row = rows[0]
    assert {
        "canonical_id",
        "model_name",
        "model_version",
        "profile_version",
        "aggregation_method",
        "interest_score",
        "computed_at",
        "input_data_hash",
    }.issubset(row)
    assert row["model_name"] == "fake-dense"


def test_candidates_without_an_abstract_are_never_scored():
    reactions = [
        EnrichedReaction(
            canonical_id=f"arxiv:{i}",
            title="Cats",
            abstract="cats and dogs",
            reaction_strength="weak",
            detected_at=NOW.isoformat(),
        )
        for i in range(MIN_REACTIONS_FOR_INFERENCE)
    ]
    no_abstract = make_paper(title="No abstract here", abstract="")
    rows = compute_predictions(
        reactions, [no_abstract], NOW, registry={"fake-dense": _FakeDenseChallenger()}
    )
    assert rows == []


def test_score_profile_is_a_weighted_average_of_similarities():
    model = _FakeDenseChallenger()
    profile = [
        ("a", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1.0),
        ("b", [0.0, 1.0, 0.0, 0.0, 0.0, 0.0], 3.0),
    ]
    paper_vector = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    score = score_profile(profile, paper_vector, model)
    assert score == 0.75  # (0*1 + 1*3) / 4
