from __future__ import annotations

from datetime import date

from paper_radar.delivery.discord_webhook import DiscordWebhook, paper_embed
from paper_radar.models import Rating
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
    assert "2026 · Nature Methods" in rendered
    assert "single-cell · formulation" in rendered
    assert paper.abstract not in rendered
    assert set(embed) <= {"title", "url", "color", "fields", "footer"}


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
