from __future__ import annotations

from datetime import UTC, datetime

from extensions.feedback.collect import run_collection
from tests.feedback.conftest import (
    BIOINFO_CHANNEL_ID,
    OTHER_USER_ID,
    SAVED_PAPERS_CHANNEL_ID,
    TARGET_USER_ID,
    FakeDiscordClient,
    make_message,
    reacting_user,
    reaction_summary,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _run(feedback_config, message, reaction_users):
    discord = FakeDiscordClient(
        messages_by_channel={BIOINFO_CHANNEL_ID: [message]},
        reaction_users=reaction_users,
    )
    from extensions.feedback.state_store import FeedbackStateStore

    state = FeedbackStateStore(feedback_config.state_dir)
    candidates = {"bioinfo": [], "ml": [], "frontier": []}
    summary = run_collection(feedback_config, discord, state, candidates, NOW)
    return summary, discord, state


def test_thumbsup_is_weak_interest_recorded_but_not_forwarded(feedback_config):
    message = make_message("100", reactions=[reaction_summary("👍")])
    reaction_users = {(BIOINFO_CHANNEL_ID, "100", "👍"): [reacting_user(TARGET_USER_ID)]}
    summary, discord, state = _run(feedback_config, message, reaction_users)

    assert summary.recorded == 1
    assert summary.forwarded == 0
    assert discord.created == []
    events = state.read_raw_events()
    assert events[0]["reaction"] == "👍"
    assert events[0]["reaction_strength"] == "weak"


def test_heart_is_medium_interest_forwarded_to_saved_papers(feedback_config):
    message = make_message("101", reactions=[reaction_summary("❤️")])
    reaction_users = {(BIOINFO_CHANNEL_ID, "101", "❤️"): [reacting_user(TARGET_USER_ID)]}
    summary, discord, state = _run(feedback_config, message, reaction_users)

    assert summary.recorded == 1
    assert summary.forwarded == 1
    assert len(discord.created) == 1
    channel_id, payload = discord.created[0]
    assert channel_id == SAVED_PAPERS_CHANNEL_ID
    events = state.read_raw_events()
    assert events[0]["reaction"] == "❤️"
    assert events[0]["reaction_strength"] == "medium"


def test_heart_fire_is_strong_interest_forwarded_to_must_read(feedback_config):
    message = make_message("102", reactions=[reaction_summary("❤️‍🔥")])
    reaction_users = {(BIOINFO_CHANNEL_ID, "102", "❤️‍🔥"): [reacting_user(TARGET_USER_ID)]}
    summary, discord, state = _run(feedback_config, message, reaction_users)

    assert summary.recorded == 1
    assert summary.forwarded == 1
    channel_id, _payload = discord.created[0]
    assert channel_id == feedback_config.must_read_channel_id
    events = state.read_raw_events()
    assert events[0]["reaction"] == "❤️‍🔥"
    assert events[0]["reaction_strength"] == "strong"


def test_unrelated_emoji_is_ignored(feedback_config):
    message = make_message("103", reactions=[reaction_summary("🔥"), reaction_summary("😀")])
    summary, discord, state = _run(feedback_config, message, reaction_users={})

    assert summary.recorded == 0
    assert summary.unrelated_emoji == 2
    assert state.read_raw_events() == []
    assert discord.created == []


def test_reaction_from_non_target_user_is_ignored(feedback_config):
    message = make_message("104", reactions=[reaction_summary("❤️")])
    reaction_users = {(BIOINFO_CHANNEL_ID, "104", "❤️"): [reacting_user(OTHER_USER_ID)]}
    summary, discord, state = _run(feedback_config, message, reaction_users)

    assert summary.recorded == 0
    assert summary.non_target_user == 1
    assert state.read_raw_events() == []
    assert discord.created == []


def test_bot_reactions_are_never_counted_as_the_target_user(feedback_config):
    message = make_message("105", reactions=[reaction_summary("❤️")])
    # Even if a bot account happened to share the target user id in the
    # reaction-user list, `bot: True` entries are excluded.
    reaction_users = {
        (BIOINFO_CHANNEL_ID, "105", "❤️"): [reacting_user(TARGET_USER_ID, bot=True)]
    }
    summary, _discord, state = _run(feedback_config, message, reaction_users)

    assert summary.recorded == 0
    assert summary.non_target_user == 1
    assert state.read_raw_events() == []


def test_papers_without_any_reaction_produce_no_event_and_are_not_negative(feedback_config):
    message = make_message("106", reactions=[])
    summary, discord, state = _run(feedback_config, message, reaction_users={})

    assert summary.recorded == 0
    assert state.read_raw_events() == []
    # There is no "negative" concept anywhere in the raw event schema.
    from extensions.feedback.events import ReactionEvent

    assert "negative" not in ReactionEvent.__dataclass_fields__
    assert not any(
        keyword in field_name
        for field_name in ReactionEvent.__dataclass_fields__
        for keyword in ("negative", "dislike")
    )
