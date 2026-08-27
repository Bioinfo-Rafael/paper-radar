from __future__ import annotations

from dataclasses import dataclass

from paper_radar.models import Paper
from paper_radar.scoring.common import contains, venue_in


@dataclass(frozen=True, slots=True)
class PaperGroup:
    name: str
    papers: list[Paper]


ML_GROUPS = (
    ("🌫 Diffusion / Score / Flow", {"diffusion", "score-based", "flow matching", "flow-matching"}),
    ("🔤 Autoregressive / Transformer", {"autoregressive", "transformer", "attention"}),
    (
        "🧱 Architecture / SSM / MoE",
        {"architecture", "state space", "state-space", "ssm", "mixture of experts", "moe"},
    ),
    (
        "🎯 Training / Objectives / Optimization",
        {"training", "objective", "optimization", "regularization", "distillation", "guidance"},
    ),
    (
        "🔬 Model Understanding / Representation",
        {
            "understanding",
            "representation",
            "mechanism",
            "phenomenon",
            "emergence",
            "internal dynamics",
        },
    ),
    (
        "📏 Evaluation / Failure Modes",
        {"evaluation", "failure mode", "failure-mode", "diagnose", "benchmark"},
    ),
    ("📐 Theory", {"theory", "theoretical", "theorem", "proof", "convergence"}),
)

FRONTIER_GROUPS = (
    (
        "🧠 Self-Improvement / AI Scientist",
        {
            "self-improvement",
            "ai-scientist",
            "self-improving",
            "ai scientist",
            "autonomous research",
        },
    ),
    (
        "🌍 World Models / Physical AI",
        {"world-model", "world model", "physical-ai", "physical ai", "embodied ai"},
    ),
    (
        "🦾 VLA / Robotics",
        {"vla", "vision-language-action", "vision language action", "robot", "robotics"},
    ),
    (
        "🤖 AI Agents",
        {"agent", "agent-capability", "agentic", "tool use", "computer use", "planning"},
    ),
    ("💭 Reasoning / Test-Time Compute", {"reasoning", "test-time compute", "test time compute"}),
    (
        "🎮 RL / Foundation Models",
        {"rl-foundation", "foundation-model", "reinforcement learning", "foundation model"},
    ),
)


def _matches(paper: Paper, terms: set[str]) -> bool:
    criteria = {item.casefold() for item in paper.matched_criteria}
    text = f"{paper.title} {paper.abstract}".casefold()
    return any(term in criteria or contains(text, term) for term in terms)


def _bucket(
    papers: list[Paper], rules: tuple[tuple[str, set[str]], ...], fallback: str
) -> list[PaperGroup]:
    buckets = {name: [] for name, _ in rules}
    buckets[fallback] = []
    for paper in papers:
        name = next((name for name, terms in rules if _matches(paper, terms)), fallback)
        buckets[name].append(paper)
    return [PaperGroup(name, grouped) for name, grouped in buckets.items() if grouped]


def group_papers(
    category: str,
    papers: list[Paper],
    venues: dict[str, list[str]] | None = None,
) -> list[PaperGroup]:
    """Group already-ranked papers for presentation without changing their order."""
    if category == "bioinfo":
        venue_config = venues or {}
        major_venues = venue_config.get("tier_s", []) + venue_config.get("tier_a", [])
        major_papers: list[Paper] = []
        direct: list[Paper] = []
        for paper in papers:
            (major_papers if venue_in(paper.venue, major_venues) else direct).append(paper)
        return [
            PaperGroup(name, grouped)
            for name, grouped in (
                ("🌟 Major Journals", major_papers),
                ("🎯 Direct Interest", direct),
            )
            if grouped
        ]
    if category == "ml":
        return _bucket(papers, ML_GROUPS, "📦 Other ML")
    if category == "frontier":
        return _bucket(papers, FRONTIER_GROUPS, "📦 Other Frontier")
    raise ValueError(f"Unknown category: {category}")
