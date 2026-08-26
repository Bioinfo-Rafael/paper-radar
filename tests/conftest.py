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
