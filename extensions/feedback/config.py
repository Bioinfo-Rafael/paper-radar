from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = ("bioinfo", "ml", "frontier")

# Concrete IDs supplied for this Discord workspace. These are not secrets
# (they are ordinary Discord snowflake IDs), so they are safe to default in
# source; every one of them can still be overridden by an environment
# variable of the same name for testing or future re-use in another guild.
DEFAULT_GUILD_ID = "1542111973397762138"
DEFAULT_SOURCE_CHANNELS: dict[str, str] = {
    "bioinfo": "1542112675188707398",
    "ml": "1542136000812163162",
    "frontier": "1542136045511118858",
}
DEFAULT_TARGET_USER_ID = "339444336905158656"
DEFAULT_SAVED_PAPERS_CHANNEL_ID = "1547153149477789786"
DEFAULT_MUST_READ_CHANNEL_ID = "1547153178091462716"

_REACTIONS_PATH = Path(__file__).with_name("reactions.yaml")


class FeedbackConfigError(RuntimeError):
    """Raised when the feedback extension cannot run in this environment."""


@dataclass(frozen=True, slots=True)
class ReactionRule:
    emoji: str
    strength_class: str
    weight: float
    forward_to: str | None


def load_reaction_rules(path: Path | None = None) -> dict[str, ReactionRule]:
    with (path or _REACTIONS_PATH).open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    rules: dict[str, ReactionRule] = {}
    for emoji, values in (payload.get("reactions") or {}).items():
        rules[emoji] = ReactionRule(
            emoji=emoji,
            strength_class=values["strength_class"],
            weight=float(values["weight"]),
            forward_to=values.get("forward_to"),
        )
    return rules


def normalize_emoji(raw: str) -> str:
    """Strip the variation-selector-16 codepoint Discord sometimes includes.

    Both '❤️' and '❤' (and the heart-on-fire equivalents) must compare equal
    so a target reaction is never missed because of serialization variance.
    """
    return (raw or "").replace("️", "")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True, slots=True)
class FeedbackConfig:
    guild_id: str
    source_channels: dict[str, str]
    target_user_id: str
    saved_papers_channel_id: str
    must_read_channel_id: str
    bot_token: str
    state_dir: Path
    username: str
    reactions: dict[str, ReactionRule]

    def rule_by_normalized_emoji(self) -> dict[str, ReactionRule]:
        return {normalize_emoji(emoji): rule for emoji, rule in self.reactions.items()}

    def category_for_channel(self, channel_id: str) -> str | None:
        for category, configured in self.source_channels.items():
            if configured == channel_id:
                return category
        return None

    @classmethod
    def from_env(cls, *, reactions_path: Path | None = None) -> FeedbackConfig:
        bot_token = os.getenv("DISCORD_BOT_TOKEN")
        if not bot_token:
            raise FeedbackConfigError("DISCORD_BOT_TOKEN is not set")
        source_channels = {
            "bioinfo": _env("BIOINFO_CHANNEL_ID", DEFAULT_SOURCE_CHANNELS["bioinfo"]),
            "ml": _env("ML_CHANNEL_ID", DEFAULT_SOURCE_CHANNELS["ml"]),
            "frontier": _env("FRONTIER_CHANNEL_ID", DEFAULT_SOURCE_CHANNELS["frontier"]),
        }
        return cls(
            guild_id=_env("DISCORD_GUILD_ID", DEFAULT_GUILD_ID),
            source_channels=source_channels,
            target_user_id=_env("TARGET_USER_ID", DEFAULT_TARGET_USER_ID),
            saved_papers_channel_id=_env(
                "SAVED_PAPERS_CHANNEL_ID", DEFAULT_SAVED_PAPERS_CHANNEL_ID
            ),
            must_read_channel_id=_env("MUST_READ_CHANNEL_ID", DEFAULT_MUST_READ_CHANNEL_ID),
            bot_token=bot_token,
            state_dir=Path(_env("FEEDBACK_STATE_DIR", "feedback-state")),
            username=_env("FEEDBACK_USERNAME", "Paper Radar Feedback"),
            reactions=load_reaction_rules(reactions_path),
        )


def default_config_dict() -> dict[str, Any]:
    """Small helper for tests/documentation: the defaults with no env overrides."""
    return {
        "guild_id": DEFAULT_GUILD_ID,
        "source_channels": dict(DEFAULT_SOURCE_CHANNELS),
        "target_user_id": DEFAULT_TARGET_USER_ID,
        "saved_papers_channel_id": DEFAULT_SAVED_PAPERS_CHANNEL_ID,
        "must_read_channel_id": DEFAULT_MUST_READ_CHANNEL_ID,
    }
