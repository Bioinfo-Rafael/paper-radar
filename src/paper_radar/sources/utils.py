from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any


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


def strip_html(value: str | None) -> str:
    return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", value or "")))


def crossref_date_parts(item: dict[str, Any]) -> date | None:
    parts = (item.get("published") or item.get("created") or {}).get("date-parts", [[]])[0]
    if not parts:
        return None
    values = [int(value) for value in parts[:3]]
    while len(values) < 3:
        values.append(1)
    try:
        return date(*values)
    except ValueError:
        return None


def crossref_abstract(value: str | None) -> str:
    return strip_html(value)


def crossref_authors(item: dict[str, Any]) -> list[str]:
    authors = [
        clean_text(" ".join(filter(None, (author.get("given"), author.get("family")))))
        for author in item.get("author") or []
    ]
    return [name for name in authors if name]
