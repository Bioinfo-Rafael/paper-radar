from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

import yaml

from paper_radar.config import RadarConfig
from paper_radar.dedup import deduplicate
from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.scoring import score_bioinfo, score_frontier, score_ml
from paper_radar.sources import (
    ArxivSource,
    BiorxivSource,
    HuggingFaceSource,
    PubMedSource,
    SemanticScholarSource,
)
from paper_radar.state import StateStore, load_candidate_cache, save_candidate_cache
from paper_radar.tuning.rules import apply_tuning, tuning_lookback_days

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RunResult:
    category: str
    candidates: list[Paper]
    selected: list[Paper]
    source_counts: dict[str, int]
    mode: Literal["daily", "more"] = "daily"


@dataclass(frozen=True, slots=True)
class SearchSettings:
    mode: Literal["daily", "more"]
    lookback_days: int
    source_limit_multiplier: int

    def scaled_limit(self, base: int, maximum: int | None = None) -> int:
        value = base * self.source_limit_multiplier
        return min(value, maximum) if maximum is not None else value


class Pipeline:
    def __init__(self, config: RadarConfig) -> None:
        self.config = config
        common = config.common
        self.client = HttpClient(common["request_timeout_seconds"], common["request_retries"])
        self.s2 = SemanticScholarSource(self.client)
        state_path = config.root / common["state"]["path"]
        self.state = StateStore(state_path, common["state"]["retention_days"])
        self.cache_path = config.root / common["state"]["candidate_cache"]

    def search_settings(self, mode: Literal["daily", "more"]) -> SearchSettings:
        values = self.config.common["search"][mode]
        return SearchSettings(
            mode=mode,
            lookback_days=int(values["lookback_days"]),
            source_limit_multiplier=int(values["source_limit_multiplier"]),
        )

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

    def acquire(
        self,
        category: str,
        today: date,
        mode: Literal["daily", "more"] = "daily",
    ) -> tuple[list[Paper], dict[str, int]]:
        search = self.search_settings(mode)
        lookback_days = tuning_lookback_days(self.config.tuning, category, search.lookback_days)
        start = today - timedelta(days=lookback_days)
        limits = self.config.common["source_limits"]
        cfg = self.config.category(category)
        groups: dict[str, list[Paper]] = {}
        if category == "bioinfo":
            groups["biorxiv"] = BiorxivSource(self.client).fetch(
                start, today, cfg["queries"]["biorxiv_categories"]
            )
            groups["pubmed"] = PubMedSource(self.client).fetch(
                cfg["queries"]["pubmed"],
                start,
                today,
                search.scaled_limit(limits["pubmed_per_query"]),
            )
            groups["semantic_scholar"] = self.s2.search(
                cfg["queries"]["semantic_scholar"],
                start,
                today,
                search.scaled_limit(limits["semantic_scholar_per_query"]),
            )
            groups["recommendations"] = self.s2.recommendations(
                self._seed_ids(category),
                search.scaled_limit(limits["semantic_scholar_recommendations"]),
            )
        elif category == "ml":
            groups["arxiv"] = ArxivSource(self.client).fetch(
                cfg["queries"]["arxiv_categories"],
                start,
                today,
                search.scaled_limit(limits["arxiv_total"]),
            )
            groups["semantic_scholar"] = self.s2.search(
                cfg["queries"]["semantic_scholar"],
                start,
                today,
                search.scaled_limit(limits["semantic_scholar_per_query"]),
            )
            groups["recommendations"] = self.s2.recommendations(
                self._seed_ids(category),
                search.scaled_limit(limits["semantic_scholar_recommendations"]),
            )
        else:
            hf_limit = search.scaled_limit(limits["huggingface"], limits.get("huggingface_max"))
            groups["huggingface"] = HuggingFaceSource().fetch(today, hf_limit)
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
        venue_config = self.config.venues.get(category, {})
        scored = [
            apply_tuning(
                paper,
                category,
                self.config.tuning,
                cfg["thresholds"],
                venue_config,
                today,
            )
            for paper in scored
        ]
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
        minimum = self._notification_threshold(category)
        return [
            paper
            for paper in ranked
            if not paper.excluded
            and paper.score >= minimum
            and not self.state.was_sent(paper, category)
        ]

    def run_daily(self, category: str, today: date) -> RunResult:
        candidates, source_counts = self.acquire(category, today, mode="daily")
        ranked = self.rank(category, candidates, today)
        return RunResult(
            category, ranked, self.select_daily(category, ranked), source_counts, mode="daily"
        )

    def run_more(self, category: str, today: date, count: int) -> RunResult:
        candidates, source_counts = self.acquire(category, today, mode="more")
        ranked = self.rank(category, candidates, today)
        selected = self.select_more(category, ranked, count)
        return RunResult(category, ranked, selected, source_counts, mode="more")

    def select_more(self, category: str, ranked: list[Paper], count: int) -> list[Paper]:
        minimum = self._notification_threshold(category)
        return [
            paper
            for paper in ranked
            if not paper.excluded
            and paper.score >= minimum
            and not self.state.was_sent(paper, category)
        ][:count]

    def _notification_threshold(self, category: str) -> float:
        base = float(self.config.category(category)["thresholds"]["more_min_score"])
        override = next(
            (
                rule
                for rule in self.config.tuning.get("thresholds", [])
                if rule.get("channel") == category
            ),
            None,
        )
        return float(override["value"]) if override else base

    def cache_results(self, today: date, results: list[RunResult]) -> None:
        existing: dict[str, list[Paper]] = {}
        for name in ("bioinfo", "ml", "frontier"):
            existing[name] = load_candidate_cache(self.cache_path, name)
        for result in results:
            minimum = self._notification_threshold(result.category)
            existing[result.category] = [
                paper
                for paper in result.candidates
                if not paper.excluded and paper.score >= minimum
            ]
        save_candidate_cache(self.cache_path, today, existing)

    def persist_state(self, today: date) -> None:
        self.state.prune(today)
        self.state.save()
