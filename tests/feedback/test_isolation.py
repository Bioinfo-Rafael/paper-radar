from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from paper_radar.config import RadarConfig
from paper_radar.pipeline import Pipeline
from tests.conftest import make_paper, stub_broad_sources

_EXTENSIONS_IMPORT_RE = re.compile(r"^\s*(import extensions\b|from extensions\b)", re.MULTILINE)


def test_paper_radar_core_never_imports_extensions(config: RadarConfig):
    src_root = config.root / "src" / "paper_radar"
    offenders = []
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _EXTENSIONS_IMPORT_RE.search(text):
            offenders.append(str(path))
    assert offenders == []


def _pipeline(config, tmp_path, monkeypatch):
    monkeypatch.setitem(config.common["state"], "path", str(tmp_path / "sent.json"))
    monkeypatch.setitem(
        config.common["state"], "candidate_cache", str(tmp_path / "candidates.json")
    )
    return Pipeline(config)


def test_daily_pipeline_is_unaffected_even_when_the_feedback_extension_is_broken(
    config, today, tmp_path, monkeypatch
):
    import extensions.feedback.collect as feedback_collect

    def boom(*args, **kwargs):
        raise RuntimeError("feedback extension exploded")

    monkeypatch.setattr(feedback_collect, "main", boom)

    pipeline = _pipeline(config, tmp_path, monkeypatch)
    stub_broad_sources(monkeypatch)
    monkeypatch.setattr(pipeline.s2, "search", lambda *a, **kw: [make_paper(title="Fine paper")])
    monkeypatch.setattr(pipeline.s2, "recommendations", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "_seed_ids", lambda category: [])

    result = pipeline.run_daily("bioinfo", today)
    assert result.category == "bioinfo"

    # The broken feedback module is still broken (proving Pipeline never
    # calls into it, rather than the breakage having been silently avoided).
    with pytest.raises(RuntimeError):
        feedback_collect.main()


def test_extensions_feedback_never_imports_scoring_or_selection_internals():
    feedback_root = Path(__file__).resolve().parents[2] / "extensions" / "feedback"
    forbidden = {"paper_radar.scoring", "paper_radar.pipeline", "paper_radar.cli"}
    for path in feedback_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden, f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"{path} imports {alias.name}"
