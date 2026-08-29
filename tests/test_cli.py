from datetime import date, datetime
from zoneinfo import ZoneInfo

from paper_radar import cli


def test_jst_default_date(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls, timezone: ZoneInfo) -> datetime:
            assert timezone.key == "Asia/Tokyo"
            return datetime(2026, 8, 28, 0, 30, tzinfo=timezone)

    monkeypatch.setattr(cli, "datetime", FakeDateTime)
    assert cli.parser().parse_args(["daily"]).date == date(2026, 8, 28)
    assert cli.parser().parse_args(["more", "--category", "bioinfo"]).date == date(2026, 8, 28)


def test_more_accepts_optional_focus():
    args = cli.parser().parse_args(
        ["more", "--category", "frontier", "--focus", "Physical AI"]
    )
    assert args.focus == "Physical AI"
