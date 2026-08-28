from __future__ import annotations

import json


def test_discord_commands_have_no_category_selector(config):
    path = config.root / "extensions/discord_more/register-command.json"
    commands = json.loads(path.read_text(encoding="utf-8"))
    assert [command["name"] for command in commands] == ["daily", "more"]
    assert all("options" not in command for command in commands)


def test_worker_uses_one_channel_mapping_for_both_commands(config):
    worker = (config.root / "extensions/discord_more/worker.js").read_text(encoding="utf-8")
    assert worker.count("env.CHANNEL_CATEGORY_MAP") == 1
    assert 'daily: { workflow: "daily.yml"' in worker
    assert 'more: { workflow: "more.yml"' in worker
    assert "interaction.channel_id" in worker
    assert "ctx.waitUntil(runCommand" in worker


def test_daily_dispatch_accepts_category_and_schedule_defaults_to_all(config):
    daily = (config.root / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    assert "options: [all, bioinfo, ml, frontier]" in daily
    assert "github.event.inputs.category || 'all'" in daily
    assert "python -m paper_radar.cli daily" in daily
    assert "--category \"${{ github.event.inputs.category || 'all' }}\"" in daily
