from __future__ import annotations

from extensions.feedback.events import ReactionEvent
from extensions.feedback.forward import build_forward_payload


def _event(**overrides) -> ReactionEvent:
    values = dict(
        event_id="abc123",
        canonical_id="arxiv:2609.02644",
        title="A great paper",
        paper_url="https://arxiv.org/abs/2609.02644",
        reaction="❤️",
        reaction_strength="medium",
        category="bioinfo",
        publication_date="2026-08-01",
        source_channel_id="1542112675188707398",
        source_message_id="999",
        source_jump_url="https://discord.com/channels/g/c/999",
        message_timestamp="2026-08-01T00:00:00+00:00",
        detected_at="2026-09-09T00:00:00+00:00",
        original_score=8.1,
        original_rating="★★★★★ Must Read",
        abstract_enrichment_status="reused_local",
        abstract_inline="the abstract",
        matched_locally=True,
        doi=None,
        arxiv_id="2609.02644",
        semantic_scholar_id=None,
    )
    values.update(overrides)
    return ReactionEvent(**values)


def test_forward_payload_reuses_original_embed_and_never_includes_the_abstract():
    original_embed = {
        "title": "A great paper",
        "url": "https://arxiv.org/abs/2609.02644",
        "color": 3066993,
        "description": "**2026-08-01 · arXiv**\n\n⭐⭐⭐⭐⭐\n\nsingle-cell",
    }
    payload = build_forward_payload(_event(), original_embed, "Paper Radar Feedback")

    embed = payload["embeds"][0]
    assert embed["title"] == "A great paper"
    assert embed["url"] == "https://arxiv.org/abs/2609.02644"
    assert embed["description"] == original_embed["description"]
    assert "the abstract" not in str(payload)
    field_names = {field["name"] for field in embed["fields"]}
    assert field_names == {"Reaction", "Category", "Source"}
    source_field = next(f for f in embed["fields"] if f["name"] == "Source")
    assert "https://discord.com/channels/g/c/999" in source_field["value"]
    assert payload["content"].startswith("❤️")
