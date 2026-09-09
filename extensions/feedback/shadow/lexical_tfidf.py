from __future__ import annotations

import math
import re
from collections import Counter

from extensions.feedback.shadow.aggregation import cosine
from extensions.feedback.shadow.interfaces import ChallengerInfo, ChallengerModel, SparseVector

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


class TFIDFChallenger(ChallengerModel):
    """Pure-Python TF-IDF / cosine-similarity baseline.

    Always available (no third-party dependency), so it is the one
    challenger every environment can actually run, including this repo's
    default test/CI setup with no ML extras installed.
    """

    info = ChallengerInfo(model_name="tfidf-lexical", model_version="1.0")
    vector_kind = "sparse"

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}

    def is_available(self) -> bool:
        return True

    def fit(self, corpus: list[str]) -> None:
        document_frequency: Counter[str] = Counter()
        for text in corpus:
            for token in set(tokenize(text)):
                document_frequency[token] += 1
        n_docs = max(1, len(corpus))
        self._idf = {
            token: math.log((n_docs + 1) / (df + 1)) + 1.0
            for token, df in document_frequency.items()
        }

    def embed(self, text: str) -> SparseVector:
        counts = Counter(tokenize(text))
        return {
            token: count * self._idf.get(token, 1.0) for token, count in counts.items()
        }

    def similarity(self, a: SparseVector, b: SparseVector) -> float:
        return cosine(a, b)
