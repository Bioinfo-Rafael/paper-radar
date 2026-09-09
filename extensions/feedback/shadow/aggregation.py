from __future__ import annotations

import math
from dataclasses import dataclass

from extensions.feedback.shadow.interfaces import ChallengerModel, Vector

# One aggregation config bundles which profile-construction strategy to use
# (weighted centroid / per-reaction-type profiles / clustering) together with
# an optional recency half-life. These axes are independent so combinations
# stay comparable rather than picking one "winning" method up front.


@dataclass(frozen=True, slots=True)
class WeightedReaction:
    vector: Vector
    weight: float
    reaction_type: str
    age_days: float


@dataclass(frozen=True, slots=True)
class AggregationConfig:
    name: str
    version: str
    method: str  # "centroid" | "per_reaction_type" | "clusters"
    half_life_days: float | None = None
    k_clusters: int = 2


def is_sparse(vector: Vector) -> bool:
    return isinstance(vector, dict)


def recency_decay(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def cosine(a: Vector, b: Vector) -> float:
    if is_sparse(a) or is_sparse(b):
        return _cosine_sparse(a, b)  # type: ignore[arg-type]
    return _cosine_dense(a, b)  # type: ignore[arg-type]


def _cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
    shared = set(a) & set(b)
    dot = sum(a[key] * b[key] for key in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def weighted_average_vector(entries: list[tuple[Vector, float]]) -> Vector:
    total_weight = sum(w for _, w in entries) or 1.0
    if is_sparse(entries[0][0]):
        out: dict[str, float] = {}
        for vector, weight in entries:
            for key, value in vector.items():  # type: ignore[union-attr]
                out[key] = out.get(key, 0.0) + value * weight
        return {key: value / total_weight for key, value in out.items()}
    length = len(entries[0][0])
    out_dense = [0.0] * length
    for vector, weight in entries:
        for index, value in enumerate(vector):  # type: ignore[arg-type]
            out_dense[index] += value * weight
    return [value / total_weight for value in out_dense]


def kmeans(vectors: list[list[float]], k: int, iterations: int = 10) -> list[list[float]]:
    """Minimal, deterministic k-means for dense vectors (pure Python, no
    numpy dependency). Seeds centroids from the first ``k`` distinct
    vectors so results are reproducible across runs with the same input.
    """
    unique: list[list[float]] = []
    for vector in vectors:
        if vector not in unique:
            unique.append(vector)
        if len(unique) == k:
            break
    centroids = unique or [vectors[0]]
    for _ in range(iterations):
        clusters: list[list[list[float]]] = [[] for _ in centroids]
        for vector in vectors:
            best = max(range(len(centroids)), key=lambda i: _cosine_dense(vector, centroids[i]))
            clusters[best].append(vector)
        new_centroids = []
        for cluster, previous in zip(clusters, centroids, strict=True):
            if not cluster:
                new_centroids.append(previous)
                continue
            new_centroids.append(
                [sum(values) / len(cluster) for values in zip(*cluster, strict=True)]
            )
        if new_centroids == centroids:
            break
        centroids = new_centroids
    return centroids


def build_profile(
    config: AggregationConfig, reactions: list[WeightedReaction]
) -> list[tuple[str, Vector, float]] | None:
    """Returns a list of (label, vector, weight) entries, or ``None`` when
    the requested method is not supported for this vector kind (e.g.
    clustering over sparse TF-IDF vectors in v1).
    """
    if not reactions:
        return None
    effective = [
        (
            r.vector,
            r.weight * recency_decay(r.age_days, config.half_life_days)
            if config.half_life_days
            else r.weight,
            r.reaction_type,
        )
        for r in reactions
    ]
    if config.method == "centroid":
        vector = weighted_average_vector([(v, w) for v, w, _ in effective])
        return [("centroid", vector, 1.0)]
    if config.method == "per_reaction_type":
        groups: dict[str, list[tuple[Vector, float]]] = {}
        for vector, weight, reaction_type in effective:
            groups.setdefault(reaction_type, []).append((vector, weight))
        return [
            (reaction_type, weighted_average_vector(items), sum(w for _, w in items))
            for reaction_type, items in groups.items()
        ]
    if config.method == "clusters":
        if is_sparse(effective[0][0]):
            return None
        vectors = [v for v, _, _ in effective]  # type: ignore[misc]
        centroids = kmeans(vectors, config.k_clusters)
        weights_by_cluster = [0.0] * len(centroids)
        for vector, weight, _ in effective:
            best = max(range(len(centroids)), key=lambda i: _cosine_dense(vector, centroids[i]))
            weights_by_cluster[best] += weight
        return [
            (f"cluster_{i}", centroid, weights_by_cluster[i] or 1.0)
            for i, centroid in enumerate(centroids)
        ]
    raise ValueError(f"Unknown aggregation method: {config.method}")


def score_profile(
    profile: list[tuple[str, Vector, float]], paper_vector: Vector, model: ChallengerModel
) -> float:
    total_weight = sum(weight for _, _, weight in profile) or 1.0
    return (
        sum(model.similarity(paper_vector, vector) * weight for _, vector, weight in profile)
        / total_weight
    )


DEFAULT_AGGREGATIONS: list[AggregationConfig] = [
    AggregationConfig(name="centroid", version="v1", method="centroid"),
    AggregationConfig(
        name="centroid_recency30d", version="v1", method="centroid", half_life_days=30.0
    ),
    AggregationConfig(name="per_reaction_type", version="v1", method="per_reaction_type"),
    AggregationConfig(name="clusters_k2", version="v1", method="clusters", k_clusters=2),
]
