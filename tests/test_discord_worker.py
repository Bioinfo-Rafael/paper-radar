from __future__ import annotations

import json


def test_discord_commands_use_channel_category_and_tune_has_feedback(config):
    path = config.root / "extensions/discord_more/register-command.json"
    commands = json.loads(path.read_text(encoding="utf-8"))
    assert [command["name"] for command in commands] == ["daily", "more", "tune"]
    assert "options" not in commands[0]
    assert commands[1]["options"] == [
        {
            "name": "focus",
            "description": "Optional topic focus for this search only",
            "type": 3,
            "required": False,
            "max_length": 200,
        }
    ]
    assert commands[2]["options"] == [
        {
            "name": "feedback",
            "description": "What should Paper Radar recommend more or less often?",
            "type": 3,
            "required": True,
            "max_length": 3500,
        }
    ]


def test_worker_uses_one_channel_mapping_for_both_commands(config):
    worker = (config.root / "extensions/discord_more/worker.js").read_text(encoding="utf-8")
    assert worker.count("env.CHANNEL_CATEGORY_MAP") == 1
    assert 'daily: { workflow: "daily.yml"' in worker
    assert 'workflow: "more.yml"' in worker
    assert 'tune: { workflow: "tune.yml"' in worker
    assert "interaction.channel_id" in worker
    assert "ctx.waitUntil(runCommand" in worker
    assert 'focus: values.focus' in worker


def test_more_workflow_passes_focus_without_shell_interpolation(config):
    workflow = (config.root / ".github/workflows/more.yml").read_text(encoding="utf-8")
    assert "MORE_FOCUS: ${{ inputs.focus }}" in workflow
    assert '--focus "$MORE_FOCUS"' in workflow
    assert '--focus "${{ inputs.focus }}"' not in workflow


def test_daily_dispatch_accepts_category_and_schedule_defaults_to_all(config):
    daily = (config.root / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    assert "options: [all, bioinfo, ml, frontier]" in daily
    assert "github.event.inputs.category || 'all'" in daily
    assert "python -m paper_radar.cli daily" in daily
    assert "--category \"${{ github.event.inputs.category || 'all' }}\"" in daily
