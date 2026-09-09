"""Regression coverage for the recent-window rescan fix.

Root cause this file guards against: an earlier implementation tracked a
per-channel last_seen_message_id cursor and only ever scanned messages
newer than it. A message is almost always reacted to *after* Paper Radar
posts it, so that message would be scanned exactly once (usually with zero
reactions), the cursor would move past it, and any reaction added later
would be permanently invisible. The fix instead rescans a fixed recent
window of each channel on every run and relies solely on the event_id /
processed_events idempotency ledger to avoid reprocessing.
"""

from __future__ import annotations

from dataclasses import replace
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
EMPTY_CANDIDATES: dict[str, list] = {"bioinfo": [], "ml": [], "frontier": []}


def test_reaction_added_after_the_initial_scan_is_still_detected_and_forwarded(feedback_config):
    """The most important regression test: post -> scan (no reaction yet)
    -> user reacts later -> next scan of the *same* message must detect and
    forward the reaction exactly once.
    """
    channel = BIOINFO_CHANNEL_ID
    state = FeedbackStateStore(feedback_config.state_dir)

    # Run 1: Paper Radar just posted the message; nobody has reacted yet.
    freshly_posted = make_message("500", reactions=[])
    run1_discord = FakeDiscordClient(messages_by_channel={channel: [freshly_posted]})
    summary1 = run_collection(feedback_config, run1_discord, state, EMPTY_CANDIDATES, NOW)
    assert summary1.recorded == 0
    assert state.read_raw_events() == []

    # Some time later, the user reacts with ❤️. The message id is unchanged
    # (it's the same Discord message) but it now carries a reaction.
    now_reacted = make_message("500", reactions=[reaction_summary("❤️")])
    reaction_users = {(channel, "500", "❤️"): [reacting_user(TARGET_USER_ID)]}

    # Run 2: nothing about state/run_collection should prevent this message
    # from being looked at again, even though run 1 already "saw" it.
    run2_discord = FakeDiscordClient(
        messages_by_channel={channel: [now_reacted]}, reaction_users=reaction_users
    )
    summary2 = run_collection(feedback_config, run2_discord, state, EMPTY_CANDIDATES, NOW)

    assert summary2.recorded == 1
    assert summary2.forwarded == 1
    assert len(run2_discord.created) == 1
    forwarded_channel_id, _payload = run2_discord.created[0]
    assert forwarded_channel_id == feedback_config.saved_papers_channel_id
    events = state.read_raw_events()
    assert len(events) == 1
    assert events[0]["reaction"] == "❤️"
    assert events[0]["source_message_id"] == "500"


def test_same_heart_rescanned_across_three_runs_forwards_only_once(feedback_config):
    channel = BIOINFO_CHANNEL_ID
    message = make_message("501", reactions=[reaction_summary("❤️")])
    reaction_users = {(channel, "501", "❤️"): [reacting_user(TARGET_USER_ID)]}
    state = FeedbackStateStore(feedback_config.state_dir)

    forwards_per_run = []
    for _ in range(3):
        discord = FakeDiscordClient(
            messages_by_channel={channel: [message]}, reaction_users=reaction_users
        )
        run_collection(feedback_config, discord, state, EMPTY_CANDIDATES, NOW)
        forwards_per_run.append(len(discord.created))

    assert forwards_per_run == [1, 0, 0]
    assert len(state.read_raw_events()) == 1


def test_thumbsup_added_after_the_fact_is_detected_on_rescan(feedback_config):
    channel = BIOINFO_CHANNEL_ID
    state = FeedbackStateStore(feedback_config.state_dir)
    unreacted = make_message("502", reactions=[])
    run_collection(
        feedback_config,
        FakeDiscordClient(messages_by_channel={channel: [unreacted]}),
        state,
        EMPTY_CANDIDATES,
        NOW,
    )
    assert state.read_raw_events() == []

    now_reacted = make_message("502", reactions=[reaction_summary("👍")])
    discord = FakeDiscordClient(
        messages_by_channel={channel: [now_reacted]},
        reaction_users={(channel, "502", "👍"): [reacting_user(TARGET_USER_ID)]},
    )
    summary = run_collection(feedback_config, discord, state, EMPTY_CANDIDATES, NOW)
    assert summary.recorded == 1
    assert summary.forwarded == 0  # 👍 is never forwarded, only recorded
    assert discord.created == []
    assert state.read_raw_events()[0]["reaction_strength"] == "weak"


def test_heart_fire_added_after_the_fact_is_detected_on_rescan(feedback_config):
    channel = BIOINFO_CHANNEL_ID
    state = FeedbackStateStore(feedback_config.state_dir)
    unreacted = make_message("503", reactions=[])
    run_collection(
        feedback_config,
        FakeDiscordClient(messages_by_channel={channel: [unreacted]}),
        state,
        EMPTY_CANDIDATES,
        NOW,
    )
    assert state.read_raw_events() == []

    now_reacted = make_message("503", reactions=[reaction_summary("❤️‍🔥")])
    discord = FakeDiscordClient(
        messages_by_channel={channel: [now_reacted]},
        reaction_users={(channel, "503", "❤️‍🔥"): [reacting_user(TARGET_USER_ID)]},
    )
    summary = run_collection(feedback_config, discord, state, EMPTY_CANDIDATES, NOW)
    assert summary.recorded == 1
    assert summary.forwarded == 1
    forwarded_channel_id, _payload = discord.created[0]
    assert forwarded_channel_id == feedback_config.must_read_channel_id
    assert state.read_raw_events()[0]["reaction_strength"] == "strong"


def test_messages_older_than_the_scan_window_are_never_scanned(feedback_config):
    channel = BIOINFO_CHANNEL_ID
    cfg = replace(feedback_config, scan_messages_per_channel=3)
    # Newest-first, exactly as Discord returns them. Only the newest 3
    # (604, 603, 602) fall inside the configured window.
    messages = [
        make_message("604", reactions=[]),
        make_message("603", reactions=[]),
        make_message("602", reactions=[]),
        make_message("601", reactions=[reaction_summary("❤️")]),
        make_message("600", reactions=[reaction_summary("❤️")]),
    ]
    reaction_users = {
        (channel, "601", "❤️"): [reacting_user(TARGET_USER_ID)],
        (channel, "600", "❤️"): [reacting_user(TARGET_USER_ID)],
    }
    state = FeedbackStateStore(cfg.state_dir)
    discord = FakeDiscordClient(
        messages_by_channel={channel: messages}, reaction_users=reaction_users
    )

    summary = run_collection(cfg, discord, state, EMPTY_CANDIDATES, NOW)

    assert summary.messages_scanned == 3
    # Both reacted messages (600, 601) sit outside the 3-message window.
    assert summary.recorded == 0
    assert state.read_raw_events() == []


def test_first_ever_run_scans_the_recent_window_without_any_priming(feedback_config):
    channel = BIOINFO_CHANNEL_ID
    message = make_message("700", reactions=[reaction_summary("❤️")])
    reaction_users = {(channel, "700", "❤️"): [reacting_user(TARGET_USER_ID)]}
    # A brand-new state store: no meta.json, no processed_events.json yet.
    state = FeedbackStateStore(feedback_config.state_dir)
    discord = FakeDiscordClient(
        messages_by_channel={channel: [message]}, reaction_users=reaction_users
    )

    summary = run_collection(feedback_config, discord, state, EMPTY_CANDIDATES, NOW)

    assert summary.recorded == 1
    assert summary.forwarded == 1


def test_a_meta_json_cursor_left_over_from_an_older_run_does_not_suppress_rescanning(
    feedback_config,
):
    """Even if a private state repo already has a last_seen_message_id-style
    entry from before this fix, it must not gate today's recent-window scan.
    """
    channel = BIOINFO_CHANNEL_ID
    state = FeedbackStateStore(feedback_config.state_dir)
    # Simulate stale legacy cursor data sitting in meta.json.
    state.set_last_seen_message_id(channel, "999999999999999999")

    message = make_message("800", reactions=[reaction_summary("❤️")])
    reaction_users = {(channel, "800", "❤️"): [reacting_user(TARGET_USER_ID)]}
    discord = FakeDiscordClient(
        messages_by_channel={channel: [message]}, reaction_users=reaction_users
    )

    summary = run_collection(feedback_config, discord, state, EMPTY_CANDIDATES, NOW)

    assert summary.recorded == 1
    assert summary.forwarded == 1
