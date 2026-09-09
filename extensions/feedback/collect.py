from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from extensions.feedback.config import (
    CATEGORIES,
    FeedbackConfig,
    FeedbackConfigError,
    normalize_emoji,
)
from extensions.feedback.discord_client import (
    DiscordClientProtocol,
    DiscordRestClient,
    fetch_new_messages,
)
from extensions.feedback.events import ReactionEvent, build_event_id, jump_url, now_iso
from extensions.feedback.forward import build_forward_payload
from extensions.feedback.identify import match_candidate
from extensions.feedback.state_store import FeedbackStateStore
from paper_radar.config import find_project_root
from paper_radar.http import HttpClient
from paper_radar.models import Paper
from paper_radar.state import load_candidate_cache

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CollectionSummary:
    messages_scanned: int = 0
    recorded: int = 0
    forwarded: int = 0
    duplicate: int = 0
    non_target_user: int = 0
    unrelated_emoji: int = 0
    queued_for_abstract: int = 0
    errors: list[str] = field(default_factory=list)


def _paper_message_embed(message: dict[str, Any]) -> dict[str, Any] | None:
    embeds = message.get("embeds") or []
    if not embeds:
        return None
    embed = embeds[0]
    if not embed.get("url") or not embed.get("title"):
        return None
    return embed


def run_collection(
    cfg: FeedbackConfig,
    discord: DiscordClientProtocol,
    state: FeedbackStateStore,
    candidates_by_category: dict[str, list[Paper]],
    now: datetime,
) -> CollectionSummary:
    summary = CollectionSummary()
    rules = cfg.rule_by_normalized_emoji()
    for category, channel_id in cfg.source_channels.items():
        after = state.last_seen_message_id(channel_id)
        messages = fetch_new_messages(discord, channel_id, after)
        newest_seen = after
        for message in messages:
            summary.messages_scanned += 1
            message_id = message["id"]
            if newest_seen is None or int(message_id) > int(newest_seen):
                newest_seen = message_id
            embed = _paper_message_embed(message)
            if embed is None:
                continue
            for reaction in message.get("reactions") or []:
                emoji = reaction.get("emoji") or {}
                if emoji.get("id"):
                    continue  # custom emoji: never one of our three targets
                normalized = normalize_emoji(emoji.get("name", ""))
                rule = rules.get(normalized)
                if rule is None:
                    summary.unrelated_emoji += 1
                    continue
                if int(reaction.get("count") or 0) < 1:
                    continue
                try:
                    users = discord.get_reaction_users(channel_id, message_id, rule.emoji)
                except Exception:
                    LOGGER.exception(
                        "Could not confirm reaction users; skipping this reaction",
                        extra={"channel_id": channel_id, "message_id": message_id},
                    )
                    summary.errors.append(f"reaction-users:{channel_id}:{message_id}")
                    continue
                user_ids = {str(user.get("id")) for user in users if not user.get("bot")}
                if cfg.target_user_id not in user_ids:
                    summary.non_target_user += 1
                    continue
                event_id = build_event_id(
                    cfg.guild_id, channel_id, message_id, cfg.target_user_id, normalized
                )
                if state.is_processed(event_id):
                    summary.duplicate += 1
                    continue
                matched = match_candidate(embed["title"], embed["url"], candidates_by_category)
                abstract_status = (
                    "reused_local"
                    if matched.abstract
                    else (
                        "pending"
                        if any((matched.doi, matched.arxiv_id, matched.semantic_scholar_id))
                        else "no_identifier"
                    )
                )
                event = ReactionEvent(
                    event_id=event_id,
                    canonical_id=matched.canonical_id,
                    title=matched.title,
                    paper_url=matched.paper_url,
                    reaction=rule.emoji,
                    reaction_strength=rule.strength_class,
                    category=matched.category or category,
                    publication_date=matched.publication_date,
                    source_channel_id=channel_id,
                    source_message_id=message_id,
                    source_jump_url=jump_url(cfg.guild_id, channel_id, message_id),
                    message_timestamp=message.get("timestamp"),
                    detected_at=now_iso(),
                    original_score=matched.score,
                    original_rating=matched.rating,
                    abstract_enrichment_status=abstract_status,
                    abstract_inline=matched.abstract,
                    matched_locally=matched.matched_locally,
                    doi=matched.doi,
                    arxiv_id=matched.arxiv_id,
                    semantic_scholar_id=matched.semantic_scholar_id,
                )
                state.append_raw_event(event)
                forwarded_to = None
                if rule.forward_to == "saved_papers":
                    forwarded_to = "saved_papers"
                    _forward(discord, cfg.saved_papers_channel_id, event, embed, cfg, summary)
                elif rule.forward_to == "must_read":
                    forwarded_to = "must_read"
                    _forward(discord, cfg.must_read_channel_id, event, embed, cfg, summary)
                state.mark_processed(event_id, forwarded_to)
                summary.recorded += 1
                if abstract_status == "pending":
                    state.enqueue_pending_abstract(matched)
                    summary.queued_for_abstract += 1
        if newest_seen and newest_seen != after:
            state.set_last_seen_message_id(channel_id, newest_seen)
    return summary


def _forward(
    discord: DiscordClientProtocol,
    channel_id: str,
    event: ReactionEvent,
    embed: dict[str, Any],
    cfg: FeedbackConfig,
    summary: CollectionSummary,
) -> None:
    try:
        discord.create_message(channel_id, build_forward_payload(event, embed, cfg.username))
        summary.forwarded += 1
    except Exception:
        LOGGER.exception(
            "Could not forward reacted paper to its destination channel",
            extra={"event_id": event.event_id, "channel_id": channel_id},
        )
        summary.errors.append(f"forward:{event.event_id}")


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    try:
        cfg = FeedbackConfig.from_env()
    except FeedbackConfigError as exc:
        LOGGER.warning("Feedback collection skipped (not configured yet): %s", exc)
        return 0
    root = find_project_root()
    candidates = {
        category: load_candidate_cache(root / "state" / "candidates.json", category)
        for category in CATEGORIES
    }
    state = FeedbackStateStore(cfg.state_dir)
    discord = DiscordRestClient(cfg.bot_token, HttpClient(timeout=25, retries=4))
    try:
        summary = run_collection(cfg, discord, state, candidates, datetime.now(UTC))
    except Exception:
        LOGGER.exception("Feedback collection failed for this run")
        return 1
    LOGGER.info("Feedback collection summary: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
