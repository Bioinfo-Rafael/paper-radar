from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from extensions.feedback.config import FeedbackConfig
from extensions.feedback.state_store import FeedbackStateStore

GUILD_ID = "1542111973397762138"
BIOINFO_CHANNEL_ID = "1542112675188707398"
ML_CHANNEL_ID = "1542136000812163162"
FRONTIER_CHANNEL_ID = "1542136045511118858"
SAVED_PAPERS_CHANNEL_ID = "1547153149477789786"
MUST_READ_CHANNEL_ID = "1547153178091462716"
TARGET_USER_ID = "339444336905158656"
OTHER_USER_ID = "111111111111111111"


class FakeDiscordClient:
    """Records every call; never touches the network."""

    def __init__(
        self,
        messages_by_channel: dict[str, list[dict[str, Any]]] | None = None,
        reaction_users: dict[tuple[str, str, str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.messages_by_channel = messages_by_channel or {}
        self.reaction_users = reaction_users or {}
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.message_calls: list[tuple[str, str | None]] = []

    def get_channel_messages(self, channel_id, after=None, limit=100):
        self.message_calls.append((channel_id, after))
        return self.messages_by_channel.get(channel_id, [])

    def get_reaction_users(self, channel_id, message_id, emoji, limit=100):
        return self.reaction_users.get((channel_id, message_id, emoji), [])

    def create_message(self, channel_id, payload):
        self.created.append((channel_id, payload))
        return {"id": f"created-{len(self.created)}", "channel_id": channel_id}


def make_message(
    message_id: str,
    title: str = "A paper",
    url: str = "https://arxiv.org/abs/2609.00001",
    reactions: list[dict[str, Any]] | None = None,
    timestamp: str = "2026-09-01T00:00:00+00:00",
) -> dict[str, Any]:
    return {
        "id": message_id,
        "timestamp": timestamp,
        "embeds": [
            {"title": title, "url": url, "color": 3066993, "description": "**2026 · arXiv**"}
        ],
        "reactions": reactions or [],
    }


def reaction_summary(emoji_name: str, count: int = 1) -> dict[str, Any]:
    return {"emoji": {"id": None, "name": emoji_name}, "count": count}


def reacting_user(user_id: str, bot: bool = False) -> dict[str, Any]:
    return {"id": user_id, "username": f"user-{user_id}", "bot": bot}


@pytest.fixture
def feedback_config(tmp_path: Path) -> FeedbackConfig:
    from extensions.feedback.config import load_reaction_rules

    reactions_path = Path(__file__).resolve().parents[2] / "extensions/feedback/reactions.yaml"
    return FeedbackConfig(
        guild_id=GUILD_ID,
        source_channels={
            "bioinfo": BIOINFO_CHANNEL_ID,
            "ml": ML_CHANNEL_ID,
            "frontier": FRONTIER_CHANNEL_ID,
        },
        target_user_id=TARGET_USER_ID,
        saved_papers_channel_id=SAVED_PAPERS_CHANNEL_ID,
        must_read_channel_id=MUST_READ_CHANNEL_ID,
        bot_token="test-token",
        state_dir=tmp_path / "feedback-state",
        username="Paper Radar Feedback",
        reactions=load_reaction_rules(reactions_path),
    )


@pytest.fixture
def feedback_state(feedback_config: FeedbackConfig) -> FeedbackStateStore:
    return FeedbackStateStore(feedback_config.state_dir)
