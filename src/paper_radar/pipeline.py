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
from paper_radar.scoring.common import venue_in
from paper_radar.sources import (
    ArxivSource,
    BiorxivSource,
    CrossrefPreprintSource,
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


@dataclass(frozen=True, slots=True)
class RetrievalLane:
    name: Literal["fresh", "backfill", "archive"]
    start: date
    end: date


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

    def retrieval_lanes(self, category: str, today: date) -> list[RetrievalLane]:
        values = self.config.common["search"]["lanes"]
        fresh_days = int(values["fresh_days"])
        backfill_days = int(values["backfill_days"])
        configured_archive = int(values["archive_days"])
        tuned_archive = tuning_lookback_days(self.config.tuning, category, configured_archive)
        archive_days = min(int(values["archive_max_days"]), tuned_archive)
        lanes = [
            RetrievalLane("fresh", today - timedelta(days=fresh_days), today),
            RetrievalLane(
                "backfill",
                today - timedelta(days=backfill_days),
                today - timedelta(days=fresh_days + 1),
            ),
        ]
        if archive_days > backfill_days and category in self.config.venues:
            lanes.append(
                RetrievalLane(
                    "archive",
                    today - timedelta(days=archive_days),
                    today - timedelta(days=backfill_days + 1),
                )
            )
        return lanes

    def _top_venues(self, category: str) -> list[str]:
        venues = self.config.venues.get(category, {})
        if category == "bioinfo":
            return venues.get("tier_s", []) + venues.get("tier_a", [])
        return venues.get("top", []) + venues.get("strong", [])

    def _acquire_lane(
        self,
        category: str,
        lane: RetrievalLane,
        search: SearchSettings,
    ) -> dict[str, list[Paper]]:
        limits = self.config.common["source_limits"]
        cfg = self.config.category(category)
        groups: dict[str, list[Paper]] = {}
        if category == "bioinfo":
            if lane.name != "archive":
                biorxiv_limit = 120 * search.source_limit_multiplier
                groups["biorxiv"] = BiorxivSource(self.client).fetch(
                    lane.start,
                    lane.end,
                    cfg["queries"]["biorxiv_categories"],
                    biorxiv_limit,
                )
                groups["crossref_preprints"] = CrossrefPreprintSource(self.client).fetch(
                    lane.start,
                    lane.end,
                    search.scaled_limit(limits["crossref_preprints"]),
                    queries=tuple(cfg["queries"]["semantic_scholar"]),
                )
                pubmed_queries = cfg["queries"]["pubmed"]
                s2_queries = cfg["queries"]["semantic_scholar"]
            else:
                pubmed_queries = cfg["queries"]["top_journal_archive"]
                s2_queries = cfg["queries"]["semantic_scholar_archive"]
            groups["pubmed"] = PubMedSource(self.client).fetch(
                pubmed_queries,
                lane.start,
                lane.end,
                search.scaled_limit(limits["pubmed_per_query"]),
            )
            groups["semantic_scholar"] = self.s2.search(
                s2_queries,
                lane.start,
                lane.end,
                search.scaled_limit(limits["semantic_scholar_per_query"]),
            )
        elif category == "ml":
            if lane.name != "archive":
                groups["arxiv"] = ArxivSource(self.client).fetch(
                    cfg["queries"]["arxiv_categories"],
                    lane.start,
                    lane.end,
                    search.scaled_limit(limits["arxiv_total"]),
                )
                s2_queries = cfg["queries"]["semantic_scholar"]
            else:
                s2_queries = cfg["queries"]["semantic_scholar_archive"]
            groups["semantic_scholar"] = self.s2.search(
                s2_queries,
                lane.start,
                lane.end,
                search.scaled_limit(limits["semantic_scholar_per_query"]),
            )
        else:
            if lane.name == "fresh":
                hf_limit = search.scaled_limit(limits["huggingface"], limits.get("huggingface_max"))
                groups["huggingface"] = HuggingFaceSource().fetch(lane.end, hf_limit)
                identifiers = [
                    f"ARXIV:{paper.arxiv_id}" for paper in groups["huggingface"] if paper.arxiv_id
                ]
                groups["semantic_scholar_enrichment"] = self.s2.fetch_batch(identifiers)
            groups["semantic_scholar"] = self.s2.search(
                cfg["queries"]["semantic_scholar"],
                lane.start,
                lane.end,
                search.scaled_limit(limits["semantic_scholar_per_query"]),
            )
        if lane.name == "archive":
            top_venues = self._top_venues(category)
            groups = {
                source: [paper for paper in papers if venue_in(paper.venue, top_venues)]
                for source, papers in groups.items()
            }
        for papers in groups.values():
            for paper in papers:
                paper.retrieval_lane = lane.name
        return groups

    def acquire(
        self,
        category: str,
        today: date,
        mode: Literal["daily", "more"] = "daily",
    ) -> tuple[list[Paper], dict[str, int]]:
        search = self.search_settings(mode)
        groups: dict[str, list[Paper]] = {}
        for lane in self.retrieval_lanes(category, today):
            for source, papers in self._acquire_lane(category, lane, search).items():
                groups[f"{lane.name}:{source}"] = papers
        if category in {"bioinfo", "ml"}:
            limits = self.config.common["source_limits"]
            recommendations = self.s2.recommendations(
                self._seed_ids(category),
                search.scaled_limit(limits["semantic_scholar_recommendations"]),
            )
            lane_values = self.config.common["search"]["lanes"]
            fresh_cutoff = today - timedelta(days=int(lane_values["fresh_days"]))
            archive_cutoff = today - timedelta(days=int(lane_values["backfill_days"]))
            top_venues = self._top_venues(category)
            kept: list[Paper] = []
            for paper in recommendations:
                if not paper.publication_date or paper.publication_date >= fresh_cutoff:
                    paper.retrieval_lane = "fresh"
                elif paper.publication_date >= archive_cutoff:
                    paper.retrieval_lane = "backfill"
                elif venue_in(paper.venue, top_venues):
                    paper.retrieval_lane = "archive"
                else:
                    continue
                kept.append(paper)
            groups["recommendations"] = kept
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
        return sorted(
            scored,
            key=lambda p: (
                p.excluded,
                -p.score,
                p.hf_rank or 9999,
                -(p.publication_date.toordinal() if p.publication_date else 0),
                p.title.casefold(),
            ),
        )

    def select_daily(self, category: str, ranked: list[Paper]) -> list[Paper]:
        fresh_target, target = self._retrieval_mix(category)
        return self._select_lanes(category, ranked, target, fresh_target)

    def _retrieval_mix(self, category: str) -> tuple[int, int]:
        defaults = self.config.common["search"]["lanes"]
        target = int(defaults["target_count"])
        fresh = int(defaults["fresh_target"])
        override = next(
            (
                rule
                for rule in self.config.tuning.get("retrieval_mix", [])
                if rule.get("channel") == category
            ),
            None,
        )
        if override:
            target = int(override["target_count"])
            fresh = int(override["fresh_count"])
        return min(fresh, target), target

    def _quality_score(self, paper: Paper) -> float:
        return paper.importance_score if paper.importance_score is not None else paper.score

    def _select_lanes(
        self,
        category: str,
        ranked: list[Paper],
        count: int,
        fresh_limit: int | None = None,
    ) -> list[Paper]:
        minimum = self._notification_threshold(category)
        eligible = [
            paper
            for paper in ranked
            if not paper.excluded
            and self._quality_score(paper) >= minimum
            and not self.state.was_sent(paper, category)
        ]
        selected: list[Paper] = []
        limits = {"fresh": fresh_limit if fresh_limit is not None else count}
        for lane in ("fresh", "backfill", "archive"):
            lane_count = 0
            for paper in eligible:
                paper_lane = paper.retrieval_lane or "fresh"
                if paper_lane == lane and paper not in selected:
                    if lane_count >= limits.get(lane, count):
                        break
                    selected.append(paper)
                    lane_count += 1
                    if len(selected) >= count:
                        return selected
        if len(selected) < count:
            for paper in eligible:
                if paper not in selected:
                    selected.append(paper)
                    if len(selected) >= count:
                        break
        return selected

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
        fresh_target, configured_target = self._retrieval_mix(category)
        proportional_fresh = min(count, round(fresh_target / max(1, configured_target) * count))
        return self._select_lanes(category, ranked, count, proportional_fresh)

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
                if not paper.excluded and self._quality_score(paper) >= minimum
            ]
        save_candidate_cache(self.cache_path, today, existing)

    def persist_state(self, today: date) -> None:
        self.state.prune(today)
        self.state.save()
