from __future__ import annotations

from extensions.feedback.discord_client import fetch_recent_messages
from tests.feedback.conftest import FakeDiscordClient

CHANNEL = "chan1"


def test_fetch_recent_messages_pages_backward_until_the_budget_is_met():
    # 12 fake messages, ids 111..100, newest (111) first.
    messages = [{"id": str(i)} for i in range(111, 99, -1)]
    discord = FakeDiscordClient(messages_by_channel={CHANNEL: messages})

    result = fetch_recent_messages(discord, CHANNEL, max_messages=5, page_size=2)

    assert [m["id"] for m in result] == ["111", "110", "109", "108", "107"]
    assert len(discord.message_calls) == 3  # batches of 2, 2, 1


def test_fetch_recent_messages_stops_early_when_the_channel_has_fewer_messages():
    messages = [{"id": str(i)} for i in range(105, 100, -1)]  # only 5 messages exist
    discord = FakeDiscordClient(messages_by_channel={CHANNEL: messages})

    result = fetch_recent_messages(discord, CHANNEL, max_messages=300, page_size=100)

    assert len(result) == 5
    assert len(discord.message_calls) == 1


def test_fetch_recent_messages_never_exceeds_the_configured_budget():
    messages = [{"id": str(i)} for i in range(1000, 900, -1)]  # 100 messages
    discord = FakeDiscordClient(messages_by_channel={CHANNEL: messages})

    result = fetch_recent_messages(discord, CHANNEL, max_messages=7, page_size=100)

    assert len(result) == 7
    assert [m["id"] for m in result] == [str(i) for i in range(1000, 993, -1)]
