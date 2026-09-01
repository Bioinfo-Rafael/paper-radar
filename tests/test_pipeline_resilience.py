from __future__ import annotations

from paper_radar.pipeline import Pipeline
from tests.conftest import make_paper, stub_broad_sources


def _pipeline(config, tmp_path, monkeypatch):
    monkeypatch.setitem(config.common["state"], "path", str(tmp_path / "sent.json"))
    monkeypatch.setitem(
        config.common["state"], "candidate_cache", str(tmp_path / "candidates.json")
    )
    return Pipeline(config)


def test_one_source_failing_does_not_stop_the_others(config, today, tmp_path, monkeypatch):
    pipeline = _pipeline(config, tmp_path, monkeypatch)
    stub_broad_sources(monkeypatch)

    good_paper = make_paper(title="A good paper", doi="10.1000/good")

    def raising_fetch(self, *args, **kwargs):
        raise RuntimeError("simulated source outage")

    import paper_radar.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module.OpenAlexSource, "search", raising_fetch)
    monkeypatch.setattr(pipeline.s2, "search", lambda *a, **kw: [good_paper])
    monkeypatch.setattr(pipeline.s2, "recommendations", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "_seed_ids", lambda category: [])

    candidates, source_counts = pipeline.acquire("bioinfo", today, mode="daily")
    assert any(paper.doi == "10.1000/good" for paper in candidates)
    health = pipeline.source_health()
    assert health.get("openalex") == "request_error"


def test_semantic_scholar_fully_down_still_yields_candidates_for_every_category(
    config, today, tmp_path, monkeypatch
):
    pipeline = _pipeline(config, tmp_path, monkeypatch)
    stub_broad_sources(monkeypatch)

    def raising(*args, **kwargs):
        raise RuntimeError("Semantic Scholar is fully down")

    monkeypatch.setattr(pipeline.s2, "search", raising)
    monkeypatch.setattr(pipeline.s2, "recommendations", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline.s2, "fetch_batch", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "_seed_ids", lambda category: [])

    import paper_radar.pipeline as pipeline_module

    other_paper = make_paper(title="Non-S2 candidate", doi="10.1000/nons2")
    monkeypatch.setattr(
        pipeline_module.PubMedSource, "fetch", lambda self, *a, **kw: [other_paper]
    )
    monkeypatch.setattr(
        pipeline_module.ArxivSource, "fetch", lambda self, *a, **kw: [other_paper]
    )

    for category in ("bioinfo", "ml", "frontier"):
        candidates, _ = pipeline.acquire(category, today, mode="daily")
        assert any(paper.doi == "10.1000/nons2" for paper in candidates), category


def test_run_parallel_isolates_task_failures(config, tmp_path, monkeypatch):
    pipeline = _pipeline(config, tmp_path, monkeypatch)

    def ok():
        return [make_paper(title="ok paper")]

    def fails():
        raise RuntimeError("boom")

    results = pipeline._run_parallel({"good": ok, "bad": fails})
    assert len(results["good"]) == 1
    assert results["bad"] == []
    assert pipeline.source_health().get("bad") == "request_error"


def test_more_mode_still_reaches_new_sources(config, today, tmp_path, monkeypatch):
    pipeline = _pipeline(config, tmp_path, monkeypatch)
    calls = []

    import paper_radar.pipeline as pipeline_module

    def recording_search(self, queries, start, end, limit):
        calls.append(limit)
        return []

    monkeypatch.setattr(pipeline_module.OpenAlexSource, "search", recording_search)
    stub_broad_sources(monkeypatch)
    monkeypatch.setattr(pipeline_module.OpenAlexSource, "search", recording_search)
    monkeypatch.setattr(pipeline.s2, "search", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline.s2, "recommendations", lambda *a, **kw: [])

    pipeline.acquire("ml", today, mode="daily")
    pipeline.acquire("ml", today, mode="more")
    assert len(calls) >= 2
    assert max(calls) > min(calls)
