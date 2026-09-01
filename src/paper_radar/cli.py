from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from paper_radar.config import load_config
from paper_radar.delivery.discord_webhook import DiscordWebhook, render_console
from paper_radar.pipeline import Pipeline, RunResult
from paper_radar.presentation import group_papers
from paper_radar.scoring.common import debug_score
from paper_radar.tuning import TuneService

LOGGER = logging.getLogger(__name__)
CATEGORIES = ("bioinfo", "ml", "frontier")
JST = ZoneInfo("Asia/Tokyo")


def jst_today() -> date:
    return datetime.now(JST).date()


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="paper-radar")
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    daily = commands.add_parser("daily", help="Fetch, rank and deliver the daily radar")
    daily.add_argument("--category", choices=(*CATEGORIES, "all"), default="all")
    daily.add_argument("--date", type=_date, default=jst_today())
    daily.add_argument("--dry-run", action="store_true")
    daily.add_argument("--debug-scores", action="store_true")
    more = commands.add_parser("more", help="Run a fresh, broader search for additional papers")
    more.add_argument("--category", choices=CATEGORIES, required=True)
    more.add_argument("--count", type=int, default=None)
    more.add_argument("--focus", default=None)
    more.add_argument("--date", type=_date, default=jst_today())
    more.add_argument("--dry-run", action="store_true")
    more.add_argument("--debug-scores", action="store_true")
    tune = commands.add_parser("tune", help="Apply natural-language preference tuning")
    tune.add_argument("--category", choices=CATEGORIES, required=True)
    tune.add_argument("--feedback", default=None)
    return root


def _deliver(
    pipeline: Pipeline,
    webhook: DiscordWebhook,
    result: RunResult,
    run_date: date,
    dry_run: bool,
    debug_scores: bool,
) -> None:
    groups = group_papers(
        result.category,
        result.selected,
        pipeline.config.venues.get(result.category),
    )
    print(
        render_console(result.category, run_date, result.selected, mode=result.mode, groups=groups)
    )
    print(f"Sources: {json.dumps(result.source_counts, sort_keys=True)}")
    print(f"Source health: {json.dumps(result.source_health, sort_keys=True)}")
    if debug_scores:
        for paper in result.candidates:
            print(json.dumps(debug_score(paper), ensure_ascii=False, sort_keys=True))
    if dry_run:
        return
    webhook.send_header(result.category, run_date, result.selected, mode=result.mode)
    degraded = [
        name
        for name, status in result.source_health.items()
        if "." not in name and status != "healthy"
    ]
    coverage_floor = int(pipeline.config.common["search"]["warning_coverage_floor"])
    if degraded and len(result.candidates) < coverage_floor:
        labels = {
            "semantic_scholar": "Semantic Scholar",
            "huggingface": "Hugging Face",
            "crossref": "Crossref",
            "biorxiv": "bioRxiv",
            "pubmed": "PubMed",
            "arxiv": "arXiv",
            "europepmc": "Europe PMC",
            "openalex": "OpenAlex",
            "openreview": "OpenReview",
            "crossref_works": "Crossref",
            "pmlr": "PMLR",
            "neurips_proceedings": "NeurIPS Proceedings",
            "cvf": "CVF Open Access",
            "acl_anthology": "ACL Anthology",
            "rss_proceedings": "RSS Proceedings",
        }
        try:
            webhook.send_message(
                result.category,
                "⚠️ Retrieval degraded: "
                + " / ".join(labels.get(name, name) for name in degraded),
            )
        except Exception:
            LOGGER.exception("Could not send retrieval health warning to Discord")
    for group in groups:
        webhook.send_group_header(result.category, group)
        for paper in group.papers:
            webhook.send_paper(result.category, paper)
            pipeline.state.mark_sent(paper, result.category)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    pipeline = Pipeline(config)
    webhook = DiscordWebhook(
        pipeline.client, config.common["discord"]["username"], config.common["discord"]["colors"]
    )
    try:
        if args.command == "tune":
            feedback = args.feedback or os.getenv("TUNE_FEEDBACK", "")
            try:
                result = TuneService(config, client=pipeline.client).tune(feedback, args.category)
            except Exception:
                LOGGER.exception("Paper Radar tuning failed; rules were not changed")
                try:
                    webhook.send_message(
                        args.category,
                        "⚠️ Paper Radarの調整に失敗しました。ルールは変更されていません。",
                    )
                except Exception:
                    LOGGER.exception("Could not send tuning failure message to Discord")
                return 1
            try:
                webhook.send_message(args.category, result.discord_message())
            except Exception:
                LOGGER.exception("Rules were updated, but Discord confirmation failed")
            return 0
        if args.command == "daily":
            categories = CATEGORIES if args.category == "all" else (args.category,)
            results = [pipeline.run_daily(category, args.date) for category in categories]
            for result in results:
                _deliver(pipeline, webhook, result, args.date, args.dry_run, args.debug_scores)
            if not args.dry_run:
                pipeline.cache_results(args.date, results)
                pipeline.persist_state(args.date)
        else:
            configured_count = config.common["search"]["more"]["count"]
            count = max(1, args.count if args.count is not None else configured_count)
            focus = args.focus.strip()[:200] if args.focus and args.focus.strip() else None
            result = pipeline.run_more(args.category, args.date, count, focus=focus)
            _deliver(pipeline, webhook, result, args.date, args.dry_run, args.debug_scores)
            if not args.dry_run:
                pipeline.persist_state(args.date)
    except Exception:
        LOGGER.exception("paper-radar failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
