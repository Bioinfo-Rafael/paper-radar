from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from paper_radar.cli import _deliver
from paper_radar.delivery.discord_webhook import (
    DiscordWebhook,
    paper_embed,
    publication_line,
    render_console,
)
from paper_radar.models import Rating
from paper_radar.pipeline import RunResult
from tests.conftest import make_paper


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))


def test_embed_contains_only_compact_required_fields():
    paper = make_paper(
        title="A method",
        abstract="This abstract must never be posted.",
        year=2026,
        venue="Nature Methods",
        matched_criteria=["single-cell", "formulation"],
        rating=Rating.MUST_READ,
    )
    embed = paper_embed(paper, 123)
    rendered = str(embed)
    assert paper.title in rendered
    assert "2026-08-24 · Nature Methods" in rendered
    assert "single-cell · formulation" in rendered
    assert "⭐⭐⭐⭐⭐" in rendered
    assert paper.abstract not in rendered
    assert not {
        "Publication",
        "Rating",
        "Matched",
        "Paper",
        "Open paper",
        "Published",
    }.intersection(rendered.split())
    assert set(embed) == {"title", "url", "color", "description"}


def test_publication_line_falls_back_to_year():
    paper = make_paper(publication_date=None, year=2025, venue="ICML")
    assert publication_line(paper) == "2025 · ICML"


@pytest.mark.parametrize(
    ("rating", "stars"),
    [
        (Rating.MUST_READ, "⭐⭐⭐⭐⭐"),
        (Rating.STRONG, "⭐⭐⭐⭐"),
        (Rating.CANDIDATE, "⭐⭐⭐"),
    ],
)
def test_rating_is_rendered_as_stars_only(rating, stars):
    rendered = paper_embed(make_paper(rating=rating), 123)["description"]
    assert stars in rendered
    assert "Must Read" not in rendered
    assert "Strong" not in rendered
    assert "Candidate" not in rendered


def test_three_category_webhooks_are_environment_only(monkeypatch):
    client = FakeClient()
    webhook = DiscordWebhook(client, "Paper Radar", {"bioinfo": 1, "ml": 2, "frontier": 3})
    for category in ("bioinfo", "ml", "frontier"):
        monkeypatch.setenv(
            f"DISCORD_{'FRONTIER' if category == 'frontier' else category.upper()}_WEBHOOK",
            f"https://example.test/{category}",
        )
        webhook.send_header(category, date(2026, 8, 26), [])
    assert [call[1] for call in client.calls] == [
        "https://example.test/bioinfo",
        "https://example.test/ml",
        "https://example.test/frontier",
    ]


def test_candidate_header_and_empty_more_message():
    candidate = make_paper(score=5, rating=Rating.CANDIDATE)
    rendered = render_console("bioinfo", date(2026, 8, 26), [candidate])
    empty = render_console("bioinfo", date(2026, 8, 26), [], mode="more")
    assert "0 Must Read · 0 Strong · 1 Candidate" in rendered
    assert "No additional qualifying papers found." in empty


def test_group_header_payload(monkeypatch):
    from paper_radar.presentation import PaperGroup

    client = FakeClient()
    webhook = DiscordWebhook(client, "Paper Radar", {"bioinfo": 1})
    monkeypatch.setenv("DISCORD_BIOINFO_WEBHOOK", "https://example.test/bioinfo")
    webhook.send_group_header("bioinfo", PaperGroup("🌟 Major Journals", [make_paper()]))
    assert client.calls[0][2]["json"]["content"] == "**🌟 Major Journals — 1 papers**"


@pytest.mark.parametrize(
    ("health", "warning"),
    [
        ({"semantic_scholar": "healthy"}, False),
        ({"semantic_scholar": "rate_limit", "pubmed": "timeout"}, True),
    ],
)
def test_retrieval_warning_only_for_degraded_sources(monkeypatch, health, warning):
    webhook = DiscordWebhook(
        FakeClient(), "Paper Radar", {"bioinfo": 1, "ml": 2, "frontier": 3}
    )
    monkeypatch.setenv("DISCORD_BIOINFO_WEBHOOK", "https://example.test/bioinfo")
    messages = []
    monkeypatch.setattr(webhook, "send_message", lambda category, content: messages.append(content))
    pipeline = SimpleNamespace(config=SimpleNamespace(venues={}), state=SimpleNamespace())
    result = RunResult("bioinfo", [], [], {}, source_health=health)
    _deliver(pipeline, webhook, result, date(2026, 8, 26), False, False)
    assert bool(messages) is warning
    if warning:
        assert messages == ["⚠️ Retrieval degraded: Semantic Scholar / PubMed"]
