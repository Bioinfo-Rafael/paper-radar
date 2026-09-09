from __future__ import annotations

from datetime import UTC, datetime

from extensions.feedback.collect import run_collection
from extensions.feedback.state_store import FeedbackStateStore
from tests.conftest import make_paper
from tests.feedback.conftest import (
    BIOINFO_CHANNEL_ID,
    TARGET_USER_ID,
    FakeDiscordClient,
    make_message,
    reacting_user,
    reaction_summary,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def test_local_abstract_is_reused_without_queueing(feedback_config):
    candidate = make_paper(
        title="A cached paper",
        paper_url="https://arxiv.org/abs/2609.02644",
        abstract="This abstract already exists locally.",
        arxiv_id="2609.02644",
    )
    message = make_message(
        "300", title="A cached paper", url="https://arxiv.org/abs/2609.02644",
        reactions=[reaction_summary("👍")],
    )
    discord = FakeDiscordClient(
        messages_by_channel={BIOINFO_CHANNEL_ID: [message]},
        reaction_users={(BIOINFO_CHANNEL_ID, "300", "👍"): [reacting_user(TARGET_USER_ID)]},
    )
    state = FeedbackStateStore(feedback_config.state_dir)
    run_collection(
        feedback_config, discord, state, {"bioinfo": [candidate], "ml": [], "frontier": []}, NOW
    )

    events = state.read_raw_events()
    assert events[0]["abstract_enrichment_status"] == "reused_local"
    assert events[0]["abstract_inline"] == "This abstract already exists locally."
    assert state.pending_papers() == {}


def test_paper_missing_locally_but_identifiable_is_queued_for_enrichment(feedback_config):
    message = make_message(
        "301", title="Not yet cached", url="https://arxiv.org/abs/2609.09999",
        reactions=[reaction_summary("👍")],
    )
    discord = FakeDiscordClient(
        messages_by_channel={BIOINFO_CHANNEL_ID: [message]},
        reaction_users={(BIOINFO_CHANNEL_ID, "301", "👍"): [reacting_user(TARGET_USER_ID)]},
    )
    state = FeedbackStateStore(feedback_config.state_dir)
    run_collection(
        feedback_config, discord, state, {"bioinfo": [], "ml": [], "frontier": []}, NOW
    )

    events = state.read_raw_events()
    assert events[0]["abstract_enrichment_status"] == "pending"
    pending = state.pending_papers()
    assert len(pending) == 1
    entry = next(iter(pending.values()))
    assert entry["arxiv_id"] == "2609.09999"
    assert entry["title"] == "Not yet cached"


def test_paper_with_no_recoverable_identifier_is_recorded_but_not_queued(feedback_config):
    message = make_message(
        "302", title="A blog-linked paper", url="https://example.test/blog/post",
        reactions=[reaction_summary("👍")],
    )
    discord = FakeDiscordClient(
        messages_by_channel={BIOINFO_CHANNEL_ID: [message]},
        reaction_users={(BIOINFO_CHANNEL_ID, "302", "👍"): [reacting_user(TARGET_USER_ID)]},
    )
    state = FeedbackStateStore(feedback_config.state_dir)
    run_collection(
        feedback_config, discord, state, {"bioinfo": [], "ml": [], "frontier": []}, NOW
    )

    events = state.read_raw_events()
    assert events[0]["abstract_enrichment_status"] == "no_identifier"
    assert state.pending_papers() == {}
