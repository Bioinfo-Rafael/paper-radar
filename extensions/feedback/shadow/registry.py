from __future__ import annotations

from extensions.feedback.shadow.embedding_models import BGESmallChallenger, Specter2Challenger
from extensions.feedback.shadow.interfaces import ChallengerModel
from extensions.feedback.shadow.lexical_tfidf import TFIDFChallenger


def build_registry() -> dict[str, ChallengerModel]:
    """No entry here is hard-coded as "the" model: this only lists every
    challenger available for side-by-side comparison. Callers must check
    ``is_available()`` themselves (or use :func:`available_models`), since
    some entries depend on optional heavy libraries that are not installed
    by default.
    """
    return {
        "tfidf-lexical": TFIDFChallenger(),
        "bge-small-en-v1.5": BGESmallChallenger(),
        "specter2-family-proxy": Specter2Challenger(),
    }


def available_models(registry: dict[str, ChallengerModel]) -> dict[str, ChallengerModel]:
    return {name: model for name, model in registry.items() if model.is_available()}
