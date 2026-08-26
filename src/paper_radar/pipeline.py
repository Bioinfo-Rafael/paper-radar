from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import yaml

from paper_radar.config import RadarConfig
from paper_radar.dedup import deduplicate
from paper_radar.http import HttpClient
from paper_radar.models import Paper, Rating
from paper_radar.scoring import score_bioinfo, score_frontier, score_ml
from paper_radar.sources import (
    ArxivSource,
    BiorxivSource,
    HuggingFaceSource,
    PubMedSource,
    SemanticScholarSource,
)
from paper_radar.state import StateStore, load_candidate_cache, save_candidate_cache

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RunResult:
    category: str
    candidates: list[Paper]
    selected: list[Paper]
    source_counts: dict[str, int]


class Pipeline:
    def __init__(self, config: RadarConfig) -> None:
        self.config = config
        common = config.common
        self.client = HttpClient(common["request_timeout_seconds"], common["request_retries"])
        self.s2 = SemanticScholarSource(self.client)
        state_path = config.root / common["state"]["path"]
        self.state = StateStore(state_path, common["state"]["retention_days"])
        self.cache_path = config.root / common["state"]["candidate_cache"]

    def _seed_ids(self, category: str) -> list[str]:
        entries = self.config.seeds.get(category, {}).get("positive", [])
        cache_path = self.config.root / "config" / "seeds.resolved.yaml"
        cache: dict[str, Any] = {}
        if cache_path.exists():
            with cache_path.open(encoding="utf-8") as handle:
                cache = yaml.safe_load(handle) or {}
        resolved = cache.setdefault(category, {})
        changed = False
        ids: list[str] = []
        for entry in entries:
            title = entry["title"]
            paper_id = entry.get("paper_id") or resolved.get(title)
            if not paper_id:
                paper_id = self.s2.resolve_seed(title)
                if paper_id:
                    resolved[title] = paper_id
                    changed = True
            if paper_id:
                ids.append(paper_id)
        if changed:
            with cache_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(cache, handle, sort_keys=True, allow_unicode=True)
        return ids

    def acquire(self, category: str, today: date) -> tuple[list[Paper], dict[str, int]]:
        lookback = self.config.common["lookback_days"]
        start = today - timedelta(days=lookback)
        limits = self.config.common["source_limits"]
        cfg = self.config.category(category)
        groups: dict[str, list[Paper]] = {}
        if category == "bioinfo":
            groups["biorxiv"] = BiorxivSource(self.client).fetch(
                start, today, cfg["queries"]["biorxiv_categories"]
            )
            groups["pubmed"] = PubMedSource(self.client).fetch(
                cfg["queries"]["pubmed"], start, today, limits["pubmed_per_query"]
            )
            groups["semantic_scholar"] = self.s2.search(
                cfg["queries"]["semantic_scholar"],
                start,
                today,
                limits["semantic_scholar_per_query"],
            )
            groups["recommendations"] = self.s2.recommendations(self._seed_ids(category))
        elif category == "ml":
            groups["arxiv"] = ArxivSource(self.client).fetch(
                cfg["queries"]["arxiv_categories"], start, today, limits["arxiv_total"]
            )
            groups["semantic_scholar"] = self.s2.search(
                cfg["queries"]["semantic_scholar"],
                start,
                today,
                limits["semantic_scholar_per_query"],
            )
            groups["recommendations"] = self.s2.recommendations(self._seed_ids(category))
        else:
            groups["huggingface"] = HuggingFaceSource().fetch(today, limits["huggingface"])
            identifiers = [f"ARXIV:{p.arxiv_id}" for p in groups["huggingface"] if p.arxiv_id]
            groups["semantic_scholar_enrichment"] = self.s2.fetch_batch(identifiers)
        source_counts = {name: len(values) for name, values in groups.items()}
        return deduplicate(paper for values in groups.values() for paper in values), source_counts

    def rank(self, category: str, papers: list[Paper], today: date) -> list[Paper]:
        cfg = self.config.category(category)
        if category == "bioinfo":
            scored = [score_bioinfo(p, cfg, self.config.venues["bioinfo"], today) for p in papers]
        elif category == "ml":
            scored = [score_ml(p, cfg, self.config.venues["ml"], today) for p in papers]
        else:
            scored = [score_frontier(p, cfg, today) for p in papers]
        if category == "frontier":
            return sorted(
                scored,
                key=lambda p: (
                    p.excluded,
                    p.hf_rank or 9999,
                    -p.score,
                    p.title.casefold(),
                ),
            )
        return sorted(
            scored,
            key=lambda p: (
                p.excluded,
                -p.score,
                -(p.publication_date.toordinal() if p.publication_date else 0),
                p.title.casefold(),
            ),
        )

    def select_daily(self, category: str, ranked: list[Paper]) -> list[Paper]:
        unseen = [p for p in ranked if not p.excluded and not self.state.was_sent(p, category)]
        must = [p for p in unseen if p.rating is Rating.MUST_READ]
        strong_limit = self.config.common["selection"]["strong_daily_limit"]
        soft_limit = self.config.common["selection"]["target_soft_limit"]
        strong_limit = min(strong_limit, max(0, soft_limit - len(must)))
        strong = [p for p in unseen if p.rating is Rating.STRONG][:strong_limit]
        return must + strong

    def run_daily(self, category: str, today: date) -> RunResult:
        candidates, source_counts = self.acquire(category, today)
        ranked = self.rank(category, candidates, today)
        return RunResult(category, ranked, self.select_daily(category, ranked), source_counts)

    def candidates_for_more(self, category: str, today: date) -> list[Paper]:
        cached = load_candidate_cache(self.cache_path, category)
        if cached:
            return cached
        candidates, _ = self.acquire(category, today)
        return self.rank(category, candidates, today)

    def select_more(self, category: str, ranked: list[Paper], count: int) -> list[Paper]:
        minimum = self.config.category(category)["thresholds"]["more_min_score"]
        return [
            paper
            for paper in ranked
            if not paper.excluded
            and paper.score >= minimum
            and not self.state.was_sent(paper, category)
        ][:count]

    def cache_results(self, today: date, results: list[RunResult]) -> None:
        existing: dict[str, list[Paper]] = {}
        for name in ("bioinfo", "ml", "frontier"):
            existing[name] = load_candidate_cache(self.cache_path, name)
        for result in results:
            minimum = self.config.category(result.category)["thresholds"]["more_min_score"]
            existing[result.category] = [
                paper
                for paper in result.candidates
                if not paper.excluded and paper.score >= minimum
            ]
        save_candidate_cache(self.cache_path, today, existing)

    def persist_state(self, today: date) -> None:
        self.state.prune(today)
        self.state.save()
