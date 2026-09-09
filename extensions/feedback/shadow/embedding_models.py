from __future__ import annotations

from extensions.feedback.shadow.aggregation import cosine
from extensions.feedback.shadow.interfaces import ChallengerInfo, ChallengerModel, DenseVector

# Both models below are optional and lazily imported. Neither dependency is
# part of this project's core install (pyproject.toml `dependencies`) nor of
# the `dev` extra used by tests/CI: they only ever load from the separate
# `feedback-embeddings` optional-dependency group, and only inside a
# feedback-specific workflow step that a maintainer opts into. If the
# libraries are absent, `is_available()` reports False and callers skip the
# model entirely rather than failing.


class _LazySentenceTransformerChallenger(ChallengerModel):
    _hf_model_name: str

    def __init__(self) -> None:
        self._model = None

    def is_available(self) -> bool:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._hf_model_name)
        return self._model

    def embed(self, text: str) -> DenseVector:
        model = self._load()
        return model.encode(text or "").tolist()

    def similarity(self, a: DenseVector, b: DenseVector) -> float:
        return cosine(a, b)


class BGESmallChallenger(_LazySentenceTransformerChallenger):
    info = ChallengerInfo(model_name="bge-small-en-v1.5", model_version="1.5")
    vector_kind = "dense"
    _hf_model_name = "BAAI/bge-small-en-v1.5"


class Specter2Challenger(_LazySentenceTransformerChallenger):
    """Scientific-paper embedding challenger.

    Uses the sentence-transformers ``allenai-specter`` checkpoint as a
    practical, easy-to-install stand-in for the SPECTER2 family (the true
    adapter-based ``allenai/specter2_base`` checkpoint needs the heavier
    `transformers` + `adapters` stack). The registry contract does not
    depend on which exact checkpoint backs this entry, so it can be swapped
    later without touching any other code.
    """

    info = ChallengerInfo(model_name="specter2-family-proxy", model_version="allenai-specter-1.0")
    vector_kind = "dense"
    _hf_model_name = "sentence-transformers/allenai-specter"
