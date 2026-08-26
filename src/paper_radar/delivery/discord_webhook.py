from __future__ import annotations

import os
from datetime import date
from typing import Any

from paper_radar.http import HttpClient
from paper_radar.models import Paper, Rating

WEBHOOK_ENV = {
    "bioinfo": "DISCORD_BIOINFO_WEBHOOK",
    "ml": "DISCORD_ML_WEBHOOK",
    "frontier": "DISCORD_FRONTIER_WEBHOOK",
}
LABELS = {
    "bioinfo": "🧬 Bioinfo Radar",
    "ml": "🧠 ML Algorithms Radar",
    "frontier": "🚀 AI Frontier Radar",
}


def render_console(category: str, run_date: date, papers: list[Paper]) -> str:
    must = sum(p.rating is Rating.MUST_READ for p in papers)
    strong = sum(p.rating is Rating.STRONG for p in papers)
    lines = [f"{LABELS[category]} — {run_date.isoformat()}", f"{must} Must Read · {strong} Strong"]
    if not papers:
        lines.append("No new papers above the notification threshold.")
    for paper in papers:
        lines.extend(
            [
                "",
                paper.rating.value,
                paper.title,
                f"{paper.year or 'Year unknown'} · {paper.venue or 'Venue unknown'}",
                f"Matched: {' · '.join(paper.matched_criteria) or 'criteria unavailable'}",
                paper.paper_url,
            ]
        )
    return "\n".join(lines)


def paper_embed(paper: Paper, color: int) -> dict[str, Any]:
    fields = [
        {
            "name": "Publication",
            "value": f"{paper.year or 'Unknown'} · {paper.venue or 'Unknown venue'}",
            "inline": False,
        },
        {"name": "Rating", "value": paper.rating.value, "inline": False},
        {
            "name": "Matched",
            "value": " · ".join(paper.matched_criteria)[:1024] or "—",
            "inline": False,
        },
        {"name": "Paper", "value": f"[Open paper]({paper.paper_url})", "inline": False},
    ]
    embed: dict[str, Any] = {
        "title": paper.title[:256],
        "url": paper.paper_url,
        "color": color,
        "fields": fields,
    }
    if paper.publication_date:
        embed["footer"] = {"text": f"Published {paper.publication_date.isoformat()}"}
    return embed


class DiscordWebhook:
    def __init__(self, client: HttpClient, username: str, colors: dict[str, int]) -> None:
        self.client = client
        self.username = username
        self.colors = colors

    def webhook_url(self, category: str) -> str:
        name = WEBHOOK_ENV[category]
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Required environment variable is not set: {name}")
        return value

    def send_header(self, category: str, run_date: date, papers: list[Paper]) -> None:
        must = sum(p.rating is Rating.MUST_READ for p in papers)
        strong = sum(p.rating is Rating.STRONG for p in papers)
        content = (
            f"**{LABELS[category]} — {run_date.isoformat()}**\n{must} Must Read · {strong} Strong"
        )
        self.client.request(
            "POST", self.webhook_url(category), json={"username": self.username, "content": content}
        )

    def send_paper(self, category: str, paper: Paper) -> None:
        payload = {"username": self.username, "embeds": [paper_embed(paper, self.colors[category])]}
        self.client.request("POST", self.webhook_url(category), json=payload)
