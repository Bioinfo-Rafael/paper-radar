from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


def build_event_id(
    guild_id: str, channel_id: str, message_id: str, user_id: str, normalized_emoji: str
) -> str:
    """Stable idempotency key.

    Derived from guild/channel/message/user/emoji as required, but the raw
    user id is only fed into the hash (never stored as a plaintext field on
    the event) since this system intentionally scopes collection to a single
    configured TARGET_USER_ID recorded once as metadata, not per-event.
    """
    raw = f"{guild_id}:{channel_id}:{message_id}:{user_id}:{normalized_emoji}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ReactionEvent:
    event_id: str
    canonical_id: str
    title: str
    paper_url: str
    reaction: str
    reaction_strength: str
    category: str | None
    publication_date: str | None
    source_channel_id: str
    source_message_id: str
    source_jump_url: str
    message_timestamp: str | None
    detected_at: str
    original_score: float | None
    original_rating: str | None
    abstract_enrichment_status: str
    abstract_inline: str
    matched_locally: bool
    doi: str | None
    arxiv_id: str | None
    semantic_scholar_id: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def jump_url(guild_id: str, channel_id: str, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
