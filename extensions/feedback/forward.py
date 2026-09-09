from __future__ import annotations

from typing import Any

from extensions.feedback.events import ReactionEvent

CATEGORY_LABELS = {"bioinfo": "Bioinfo", "ml": "ML Algorithms", "frontier": "AI Frontier"}


def build_forward_payload(
    event: ReactionEvent, original_embed: dict[str, Any], username: str
) -> dict[str, Any]:
    """Reuse the existing paper embed (title/url/color/description) and add
    only what it doesn't already carry: the reaction, category, and a jump
    link back to the original message. No abstract text is ever included.
    """
    embed = dict(original_embed)
    category_label = CATEGORY_LABELS.get(event.category or "", event.category or "Unknown")
    embed["fields"] = [
        {"name": "Reaction", "value": event.reaction, "inline": True},
        {"name": "Category", "value": category_label, "inline": True},
        {
            "name": "Source",
            "value": f"[Jump to original message]({event.source_jump_url})",
            "inline": False,
        },
    ]
    return {
        "username": username,
        "content": f"{event.reaction} {event.title}",
        "embeds": [embed],
    }
