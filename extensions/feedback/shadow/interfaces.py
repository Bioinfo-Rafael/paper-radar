from __future__ import annotations

from dataclasses import dataclass

DenseVector = list[float]
SparseVector = dict[str, float]
Vector = DenseVector | SparseVector


@dataclass(frozen=True, slots=True)
class ChallengerInfo:
    model_name: str
    model_version: str


class ChallengerModel:
    """Base interface every semantic-interest challenger implements.

    This is a shadow/experimental interface only: nothing in
    ``src/paper_radar`` depends on it, and no implementation here is ever
    treated as the "correct" one — the registry exists precisely so several
    can be compared side by side.
    """

    info: ChallengerInfo
    vector_kind: str = "dense"  # "dense" or "sparse"

    def is_available(self) -> bool:
        raise NotImplementedError

    def fit(self, corpus: list[str]) -> None:
        """Optional corpus-level fitting (e.g. TF-IDF vocabulary/IDF)."""

    def embed(self, text: str) -> Vector:
        raise NotImplementedError

    def similarity(self, a: Vector, b: Vector) -> float:
        raise NotImplementedError
