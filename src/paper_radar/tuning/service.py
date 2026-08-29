from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

from paper_radar.config import RadarConfig
from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.sources.semantic_scholar import SemanticScholarSource
from paper_radar.state import load_candidate_cache
from paper_radar.tuning.groq import ACTION_TYPES, CATEGORIES, SIGNAL_TARGETS, GroqTuneClient


@dataclass(frozen=True, slots=True)
class TuneResult:
    summary: str
    warnings: list[str]
    applied_actions: int

    def discord_message(self) -> str:
        heading = (
            "🔧 **Paper Radarを更新しました**"
            if self.applied_actions
            else "⚠️ **Paper Radarは変更しませんでした**"
        )
        lines = [heading, "", self.summary]
        if self.warnings:
            lines.extend(["", f"⚠️ 変更しなかった項目: {' / '.join(self.warnings)}"])
        if self.applied_actions:
            lines.extend(["", "次回の探索から反映されます。"])
        return "\n".join(lines)[:2000]


class TuneValidationError(ValueError):
    pass


def _clean_text(value: Any, name: str, maximum: int = 120) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TuneValidationError(f"{name} is required")
    return " ".join(value.split())[:maximum]


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TuneValidationError(f"{name} must be numeric")
    if not minimum <= float(value) <= maximum:
        raise TuneValidationError(f"{name} must be between {minimum} and {maximum}")
    return float(value)


def validate_action(action: Any, config: RadarConfig) -> dict[str, Any]:
    if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
        raise TuneValidationError("unknown action type")
    action_type = action["type"]
    channel = action.get("channel")
    if action_type != "set_routing" and channel not in CATEGORIES:
        raise TuneValidationError("valid channel is required")
    clean: dict[str, Any] = {"type": action_type}

    if action_type in {"add_concept", "remove_concept", "change_concept_weight"}:
        clean.update(channel=channel, concept=_clean_text(action.get("concept"), "concept"))
        if action_type == "add_concept":
            polarity = action.get("polarity")
            if polarity not in {"positive", "negative"}:
                raise TuneValidationError("polarity must be positive or negative")
            keywords = action.get("keywords")
            if not isinstance(keywords, list) or not keywords:
                raise TuneValidationError("at least one keyword is required")
            clean.update(
                polarity=polarity,
                keywords=list(dict.fromkeys(_clean_text(item, "keyword", 80) for item in keywords))[
                    :12
                ],
                weight=_number(action.get("amount"), "amount", 0.1, 5),
            )
        elif action_type == "change_concept_weight":
            clean["weight"] = _number(action.get("amount"), "amount", 0.1, 5)
    elif action_type == "adjust_signal_weight":
        if action.get("target") not in SIGNAL_TARGETS:
            raise TuneValidationError("invalid signal target")
        clean.update(
            channel=channel,
            target=action["target"],
            amount=_number(action.get("amount"), "amount", -3, 3),
        )
    elif action_type == "set_journal_priority":
        journal = action.get("journal")
        group = action.get("journal_group")
        if not journal and not group:
            raise TuneValidationError("journal or journal_group is required")
        clean.update(
            channel=channel,
            journal=_clean_text(journal, "journal") if journal else None,
            journal_group=_clean_text(group, "journal_group") if group else None,
            weight=_number(action.get("amount"), "amount", -3, 3),
        )
    elif action_type == "set_freshness":
        clean.update(
            channel=channel,
            days=int(_number(action.get("days"), "days", 1, 1825)),
            weight=_number(action.get("amount"), "amount", 0, 3),
        )
    elif action_type == "set_backfill":
        group = action.get("journal_group")
        journal = action.get("journal")
        if not group and not journal:
            raise TuneValidationError("journal or journal_group is required")
        clean.update(
            channel=channel,
            journal_group=_clean_text(group, "journal_group") if group else None,
            journal=_clean_text(journal, "journal") if journal else None,
            days=int(_number(action.get("days"), "days", 1, 1825)),
            priority=_number(action.get("amount"), "amount", -3, 3),
        )
    elif action_type == "set_routing":
        preferred = action.get("preferred_channel")
        if preferred not in CATEGORIES:
            raise TuneValidationError("preferred_channel is required")
        keywords = action.get("keywords")
        if not isinstance(keywords, list) or not keywords:
            raise TuneValidationError("routing keywords are required")
        clean.update(
            concept=_clean_text(action.get("concept"), "concept"),
            keywords=list(dict.fromkeys(_clean_text(item, "keyword", 80) for item in keywords))[
                :12
            ],
            preferred_channel=preferred,
        )
    elif action_type == "set_notification_threshold":
        strong = float(config.category(channel)["thresholds"]["strong"])
        clean.update(
            channel=channel,
            value=_number(action.get("threshold"), "threshold", 0, strong - 0.001),
        )
    elif action_type == "set_type_preference":
        clean.update(
            channel=channel,
            paper_type=_clean_text(action.get("paper_type"), "paper_type"),
            weight=_number(action.get("amount"), "amount", -3, 3),
        )
    return clean


COLLECTION_KEYS = {
    "add_concept": "concepts",
    "remove_concept": "concepts",
    "change_concept_weight": "concepts",
    "adjust_signal_weight": "signal_adjustments",
    "set_journal_priority": "journal_priorities",
    "set_freshness": "freshness",
    "set_backfill": "backfill",
    "set_routing": "routing",
    "set_notification_threshold": "thresholds",
    "set_type_preference": "type_preferences",
}


def _identity(action: dict[str, Any]) -> tuple[Any, ...]:
    kind = action["type"]
    if kind in {"add_concept", "remove_concept", "change_concept_weight"}:
        return action.get("channel"), action.get("concept", "").casefold()
    if kind == "adjust_signal_weight":
        return action["channel"], action["target"]
    if kind in {"set_journal_priority", "set_backfill"}:
        return action["channel"], action.get("journal_group"), action.get("journal")
    if kind in {"set_freshness", "set_notification_threshold"}:
        return (action["channel"],)
    if kind == "set_routing":
        return (action["concept"].casefold(),)
    return action["channel"], action["paper_type"].casefold()


def apply_actions(rules: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    updated = copy.deepcopy(rules)
    for action in actions:
        key = COLLECTION_KEYS[action["type"]]
        collection = updated.setdefault(key, [])
        identity = _identity(action)
        existing = next(
            (
                item
                for item in collection
                if _identity({"type": action["type"], **item}) == identity
            ),
            None,
        )
        if action["type"] == "remove_concept":
            if existing:
                collection.remove(existing)
            continue
        if action["type"] == "change_concept_weight":
            if not existing:
                raise TuneValidationError(f"concept does not exist: {action['concept']}")
            existing["weight"] = action["weight"]
            continue
        stored = {name: value for name, value in action.items() if name != "type"}
        if existing:
            existing.clear()
            existing.update(stored)
        else:
            collection.append(stored)
    return updated


class TuneService:
    def __init__(
        self,
        config: RadarConfig,
        groq: GroqTuneClient | None = None,
        client: HttpClient | None = None,
    ) -> None:
        self.config = config
        self.groq = groq or GroqTuneClient()
        self.s2 = SemanticScholarSource(client or HttpClient())
        self.rules_path = config.root / "config/tuning.yaml"
        self.history_path = config.root / "state/tuning_history.json"

    def _recent_papers(self) -> list[Paper]:
        path = self.config.root / self.config.common["state"]["candidate_cache"]
        return [paper for category in CATEGORIES for paper in load_candidate_cache(path, category)]

    @staticmethod
    def _identifier(url: str) -> str | None:
        lower = url.casefold()
        if "arxiv.org/" in lower:
            match = re.search(r"(?:abs|pdf)/(\d{4}\.\d{4,5})", url, re.I)
            return f"ARXIV:{match.group(1)}" if match else None
        if "doi.org/" in lower:
            return f"DOI:{url.split('doi.org/', 1)[1].split('?', 1)[0]}"
        if "biorxiv.org/content/" in lower:
            match = re.search(r"(10\.1101/[^/?#]+)", url, re.I)
            return f"DOI:{match.group(1)}" if match else None
        if "semanticscholar.org/paper/" in lower:
            paper_id = url.rstrip("/").split("/")[-1].split("?")[0]
            return paper_id if re.fullmatch(r"[a-fA-F0-9]{40}", paper_id) else None
        return None

    def resolve_papers(self, feedback: str) -> list[Paper]:
        recent = self._recent_papers()
        feedback_folded = feedback.casefold()
        found: dict[str, Paper] = {}
        urls = re.findall(r"https?://[^\s<>]+", feedback)
        for paper in recent:
            url_match = any(url.rstrip(".,。)") in paper.paper_url for url in urls)
            title_words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{5,}", paper.title)
            title_match = any(word.casefold() in feedback_folded for word in title_words)
            if url_match or title_match:
                found[paper.canonical_id or paper.title] = paper
        for url in urls:
            if any(url.rstrip(".,。)") in paper.paper_url for paper in found.values()):
                continue
            identifier = self._identifier(url.rstrip(".,。)"))
            paper = self.s2.fetch_by_id(identifier) if identifier else None
            if paper:
                found[paper.canonical_id or paper.title] = paper
        return list(found.values())[:8]

    def _rules_for_prompt(self) -> dict[str, Any]:
        return {
            "tuning": self.config.tuning,
            "base_category_rules": self.config.categories,
            "venues": self.config.venues,
            "search": self.config.common["search"],
        }

    def tune(self, feedback: str, channel: str) -> TuneResult:
        feedback = feedback.strip()
        if not 1 <= len(feedback) <= 3500:
            raise TuneValidationError("feedback must contain 1 to 3500 characters")
        if channel not in CATEGORIES:
            raise TuneValidationError("unknown channel")
        papers = self.resolve_papers(feedback)
        paper_payload = [
            {
                "title": paper.title,
                "abstract": paper.abstract[:2000],
                "venue": paper.venue,
                "publication_date": paper.publication_date.isoformat()
                if paper.publication_date
                else None,
                "url": paper.paper_url,
                "current_matches": paper.matched_criteria,
            }
            for paper in papers
        ]
        proposal = self.groq.propose(feedback, paper_payload, self._rules_for_prompt())
        before = copy.deepcopy(self.config.tuning)
        valid: list[dict[str, Any]] = []
        warnings = [str(item)[:200] for item in proposal.get("warnings", []) if str(item)]
        for index, action in enumerate(proposal.get("actions", []), 1):
            try:
                valid.append(validate_action(action, self.config))
            except TuneValidationError as exc:
                warnings.append(f"action {index}: {exc}")
        after = apply_actions(before, valid)
        summary = _clean_text(proposal.get("summary"), "summary", 800)
        if not valid:
            summary = "有効なルール変更はありませんでした。"
        self._persist(feedback, before, after, summary, warnings, valid, channel)
        return TuneResult(summary, warnings, len(valid))

    def _persist(
        self,
        feedback: str,
        before: dict[str, Any],
        after: dict[str, Any],
        summary: str,
        warnings: list[str],
        actions: list[dict[str, Any]],
        channel: str,
    ) -> None:
        history = {"version": 1, "entries": []}
        if self.history_path.exists():
            history = json.loads(self.history_path.read_text(encoding="utf-8"))
        history.setdefault("entries", []).append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "channel": channel,
                "original_tune_message": feedback,
                "before": before,
                "after": after,
                "summary": summary,
                "warnings": warnings,
                "actions": actions,
            }
        )
        rules_temp = self.rules_path.with_suffix(".yaml.tmp")
        history_temp = self.history_path.with_suffix(".json.tmp")
        rules_temp.write_text(
            yaml.safe_dump(after, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        history_temp.write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        rules_temp.replace(self.rules_path)
        history_temp.replace(self.history_path)
