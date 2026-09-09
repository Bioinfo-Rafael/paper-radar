from __future__ import annotations

from datetime import UTC, datetime

from extensions.feedback.collect import run_collection
from extensions.feedback.state_store import FeedbackStateStore
from tests.feedback.conftest import (
    BIOINFO_CHANNEL_ID,
    TARGET_USER_ID,
    FakeDiscordClient,
    make_message,
    reacting_user,
    reaction_summary,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def test_duplicate_reaction_seen_twice_is_recorded_only_once(feedback_config):
    message = make_message("200", reactions=[reaction_summary("❤️")])
    reaction_users = {(BIOINFO_CHANNEL_ID, "200", "❤️"): [reacting_user(TARGET_USER_ID)]}
    state = FeedbackStateStore(feedback_config.state_dir)
    candidates = {"bioinfo": [], "ml": [], "frontier": []}

    def discord_seeing_the_same_message_again():
        # Simulate the 30-minute poll observing the same still-recent
        # message with the same reaction a second time.
        return FakeDiscordClient(
            messages_by_channel={BIOINFO_CHANNEL_ID: [message]}, reaction_users=reaction_users
        )

    first_summary = run_collection(
        feedback_config, discord_seeing_the_same_message_again(), state, candidates, NOW
    )
    second_discord = discord_seeing_the_same_message_again()
    second_summary = run_collection(feedback_config, second_discord, state, candidates, NOW)

    assert first_summary.recorded == 1
    assert second_summary.recorded == 0
    assert second_summary.duplicate == 1
    assert len(state.read_raw_events()) == 1


def test_duplicate_reaction_never_forwards_to_saved_papers_twice(feedback_config):
    message = make_message("201", reactions=[reaction_summary("❤️")])
    reaction_users = {(BIOINFO_CHANNEL_ID, "201", "❤️"): [reacting_user(TARGET_USER_ID)]}
    state = FeedbackStateStore(feedback_config.state_dir)
    candidates = {"bioinfo": [], "ml": [], "frontier": []}

    first_discord = FakeDiscordClient(
        messages_by_channel={BIOINFO_CHANNEL_ID: [message]}, reaction_users=reaction_users
    )
    run_collection(feedback_config, first_discord, state, candidates, NOW)
    assert len(first_discord.created) == 1

    second_discord = FakeDiscordClient(
        messages_by_channel={BIOINFO_CHANNEL_ID: [message]}, reaction_users=reaction_users
    )
    run_collection(feedback_config, second_discord, state, candidates, NOW)
    assert second_discord.created == []
