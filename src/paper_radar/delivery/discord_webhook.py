from __future__ import annotations

import os
from datetime import date
from typing import Any

from paper_radar.http import HttpClient
from paper_radar.models import Paper, Rating
from paper_radar.presentation import PaperGroup

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
RATING_STARS = {
    Rating.MUST_READ: "⭐⭐⭐⭐⭐",
    Rating.STRONG: "⭐⭐⭐⭐",
    Rating.CANDIDATE: "⭐⭐⭐",
}


def publication_line(paper: Paper) -> str:
    published = (
        paper.publication_date.isoformat()
        if paper.publication_date
        else str(paper.year or "Unknown")
    )
    return f"{published} · {paper.venue or 'Unknown venue'}"


def _rating_counts(papers: list[Paper]) -> tuple[int, int, int]:
    must = sum(p.rating is Rating.MUST_READ for p in papers)
    strong = sum(p.rating is Rating.STRONG for p in papers)
    candidate = sum(p.rating is Rating.CANDIDATE for p in papers)
    return must, strong, candidate


def render_console(
    category: str,
    run_date: date,
    papers: list[Paper],
    mode: str = "daily",
    groups: list[PaperGroup] | None = None,
) -> str:
    must, strong, candidate = _rating_counts(papers)
    lines = [
        f"{LABELS[category]} — {run_date.isoformat()}",
        f"{must} Must Read · {strong} Strong · {candidate} Candidate",
    ]
    if not papers:
        lines.append(
            "No additional qualifying papers found."
            if mode == "more"
            else "No new papers above the notification threshold."
        )
    presented = groups or ([PaperGroup("", papers)] if papers else [])
    for group in presented:
        if group.name:
            lines.extend(["", f"{group.name} — {len(group.papers)} papers"])
        for paper in group.papers:
            lines.extend(
                [
                    "",
                    paper.title,
                    publication_line(paper),
                    RATING_STARS.get(paper.rating, ""),
                    " · ".join(paper.matched_criteria) or "—",
                    paper.paper_url,
                ]
            )
    return "\n".join(lines)


def paper_embed(paper: Paper, color: int) -> dict[str, Any]:
    description = "\n\n".join(
        (
            f"**{publication_line(paper)}**",
            RATING_STARS.get(paper.rating, ""),
            (" · ".join(paper.matched_criteria) or "—"),
        )
    )
    embed: dict[str, Any] = {
        "title": paper.title[:256],
        "url": paper.paper_url,
        "color": color,
        "description": description[:4096],
    }
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

    def send_header(
        self,
        category: str,
        run_date: date,
        papers: list[Paper],
        mode: str = "daily",
    ) -> None:
        must, strong, candidate = _rating_counts(papers)
        content = (
            f"**{LABELS[category]} — {run_date.isoformat()}**\n"
            f"{must} Must Read · {strong} Strong · {candidate} Candidate"
        )
        if not papers:
            content += (
                "\nNo additional qualifying papers found."
                if mode == "more"
                else "\nNo new papers above the notification threshold."
            )
        self.client.request(
            "POST", self.webhook_url(category), json={"username": self.username, "content": content}
        )

    def send_paper(self, category: str, paper: Paper) -> None:
        payload = {"username": self.username, "embeds": [paper_embed(paper, self.colors[category])]}
        self.client.request("POST", self.webhook_url(category), json=payload)

    def send_group_header(self, category: str, group: PaperGroup) -> None:
        payload = {
            "username": self.username,
            "content": f"**{group.name} — {len(group.papers)} papers**",
        }
        self.client.request("POST", self.webhook_url(category), json=payload)
