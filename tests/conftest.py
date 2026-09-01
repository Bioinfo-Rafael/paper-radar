from __future__ import annotations

from datetime import date

import pytest

from paper_radar.config import RadarConfig, load_config
from paper_radar.models import Paper


@pytest.fixture(scope="session")
def config() -> RadarConfig:
    return load_config()


@pytest.fixture
def today() -> date:
    return date(2026, 8, 26)


def make_paper(**overrides: object) -> Paper:
    values: dict[str, object] = {
        "title": "A paper",
        "abstract": "",
        "publication_date": date(2026, 8, 24),
        "venue": "bioRxiv",
        "paper_url": "https://example.test/paper",
        "source": "test",
    }
    values.update(overrides)
    return Paper(**values)  # type: ignore[arg-type]


def stub_broad_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every source class other than Semantic Scholar to return no
    results, so tests exercising `Pipeline.acquire`/`_acquire_lane` without
    mocking every individual source stay network-free. Semantic Scholar is
    left alone since most such tests mock `pipeline.s2` directly.
    """
    import paper_radar.pipeline as pipeline_module

    for class_name, method in (
        ("ArxivSource", "fetch"),
        ("HuggingFaceSource", "fetch"),
        ("EuropePMCSource", "fetch"),
        ("OpenAlexSource", "search"),
        ("OpenReviewSource", "search"),
        ("CrossrefWorksSource", "fetch"),
        ("CrossrefPreprintSource", "fetch"),
        ("BiorxivSource", "fetch"),
        ("PubMedSource", "fetch"),
        ("PMLRSource", "fetch"),
        ("NeurIPSProceedingsSource", "fetch"),
        ("CVFSource", "fetch"),
        ("ACLAnthologySource", "fetch"),
        ("RSSProceedingsSource", "fetch"),
    ):
        monkeypatch.setattr(
            getattr(pipeline_module, class_name), method, lambda self, *a, **kw: []
        )
