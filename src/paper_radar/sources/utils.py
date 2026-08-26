from __future__ import annotations

from datetime import date, datetime


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for date_format in ("%Y-%b-%d", "%Y-%B-%d", "%Y %b %d", "%Y %B %d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            pass
    for candidate in (value[:10], value[:7], value[:4]):
        try:
            if len(candidate) == 10:
                return date.fromisoformat(candidate)
            if len(candidate) == 7:
                return datetime.strptime(candidate, "%Y-%m").date()
            if len(candidate) == 4:
                return date(int(candidate), 1, 1)
        except ValueError:
            continue
    return None


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())
