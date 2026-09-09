from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

from paper_radar.http import HttpClient

API_BASE = "https://discord.com/api/v10"


class DiscordClientProtocol(Protocol):
    """Duck-typed surface used by collect.py, easy to fake in tests."""

    def get_channel_messages(
        self, channel_id: str, after: str | None = None, limit: int = 100
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
        self, channel_id: str, after: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if after:
            params["after"] = after
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


def fetch_new_messages(
    discord: DiscordClientProtocol,
    channel_id: str,
    after: str | None,
    *,
    page_size: int = 100,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """Page forward through channel history since ``after`` (or, if ``after``
    is None, just the most recent page — a fresh channel is never fully
    backfilled to bound API usage on the very first run).
    """
    if after is None:
        # First run for this channel: only look at the current tail rather
        # than walking the entire channel history.
        return discord.get_channel_messages(channel_id, after=None, limit=page_size)
    messages: list[dict[str, Any]] = []
    cursor = after
    for _ in range(max_pages):
        batch = discord.get_channel_messages(channel_id, after=cursor, limit=page_size)
        if not batch:
            break
        messages.extend(batch)
        newest = max(batch, key=lambda item: int(item["id"]))
        cursor = newest["id"]
        if len(batch) < page_size:
            break
    return messages
