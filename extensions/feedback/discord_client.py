from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

from paper_radar.http import HttpClient

API_BASE = "https://discord.com/api/v10"


class DiscordClientProtocol(Protocol):
    """Duck-typed surface used by collect.py, easy to fake in tests."""

    def get_channel_messages(
        self,
        channel_id: str,
        after: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def get_reaction_users(
        self, channel_id: str, message_id: str, emoji: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    def create_message(self, channel_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class DiscordRestClient:
    """Thin REST wrapper around the Discord bot token.

    Deliberately request/response based (no Gateway connection): reaction
    state is polled periodically by a GitHub Actions workflow rather than
    held open by a persistent bot process.
    """

    def __init__(self, bot_token: str, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()
        self.headers = {"Authorization": f"Bot {bot_token}"}

    def get_channel_messages(
        self,
        channel_id: str,
        after: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        response = self.client.request(
            "GET",
            f"{API_BASE}/channels/{channel_id}/messages",
            headers=self.headers,
            params=params,
            health_key="discord.messages",
        )
        return response.json()

    def get_reaction_users(
        self, channel_id: str, message_id: str, emoji: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        encoded_emoji = quote(emoji, safe="")
        response = self.client.request(
            "GET",
            f"{API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}",
            headers=self.headers,
            params={"limit": limit},
            health_key="discord.reactions",
        )
        return response.json()

    def create_message(self, channel_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.request(
            "POST",
            f"{API_BASE}/channels/{channel_id}/messages",
            headers=self.headers,
            json=payload,
            health_key="discord.create_message",
        )
        return response.json()


def fetch_recent_messages(
    discord: DiscordClientProtocol,
    channel_id: str,
    max_messages: int,
    *,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch the channel's ``max_messages`` most recent messages, newest
    first, paging backward with ``before`` (Discord's messages endpoint caps
    a single page at 100).

    Deliberately NOT a "since last seen" cursor walk: reactions are added to
    a message well after it was posted, so a message that scrolled out of
    this window on an earlier run would otherwise never be reaction-checked
    again. Every run rescans this same recent window regardless of what a
    previous run saw; extensions.feedback.collect's event_id/
    processed_events idempotency ledger — not this function — is what
    prevents reprocessing a reaction already recorded.
    """
    messages: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(messages) < max_messages:
        remaining = max_messages - len(messages)
        batch = discord.get_channel_messages(
            channel_id, before=cursor, limit=min(page_size, remaining)
        )
        if not batch:
            break
        messages.extend(batch)
        oldest = min(batch, key=lambda item: int(item["id"]))
        cursor = oldest["id"]
        if len(batch) < min(page_size, remaining):
            break
    return messages
