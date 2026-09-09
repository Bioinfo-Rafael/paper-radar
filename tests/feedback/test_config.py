from __future__ import annotations

from extensions.feedback.config import DEFAULT_SCAN_MESSAGES_PER_CHANNEL, FeedbackConfig


def test_scan_messages_per_channel_defaults_to_300(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.delenv("REACTION_SCAN_MESSAGES_PER_CHANNEL", raising=False)
    cfg = FeedbackConfig.from_env()
    assert cfg.scan_messages_per_channel == DEFAULT_SCAN_MESSAGES_PER_CHANNEL == 300


def test_scan_messages_per_channel_is_configurable_via_env(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("REACTION_SCAN_MESSAGES_PER_CHANNEL", "750")
    cfg = FeedbackConfig.from_env()
    assert cfg.scan_messages_per_channel == 750
