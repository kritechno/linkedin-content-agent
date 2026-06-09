"""Orchestration: research → draft → review queue, plus publishing.

Framework-agnostic on purpose — the Telegram bot and the dry-run CLI both call
into here, so the review UI and the core logic stay decoupled.
"""

from __future__ import annotations

from dataclasses import dataclass

from linkedin_agent.config import Settings, get_settings
from linkedin_agent.draft import writer
from linkedin_agent.draft.llm import LLMProvider, get_provider
from linkedin_agent.enrich import images
from linkedin_agent.research.engine import get_top_topics
from linkedin_agent.research.models import Story
from linkedin_agent import feedback, store


@dataclass
class CycleResult:
    draft_ids: list[int]
    skipped_seen: int
    considered: int


def image_card_text(record: store.DraftRecord) -> str:
    """Text proposed for the image card.

    Use the first visible line of the effective post so manual edits naturally
    change the card proposal before the PNG is rendered.
    """
    for line in record.effective_text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return record.current_angle.hook.strip()


def run_cycle(
    *,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    force_mock: bool = False,
    topics_limit: int | None = None,
    enrich: bool | None = None,
) -> CycleResult:
    """Pull topics, draft the freshest unseen ones, persist them as pending
    review items. Returns the new draft ids."""
    settings = settings or get_settings()
    provider = provider or get_provider(settings, force_mock=force_mock)
    topics_limit = topics_limit or settings.topics_per_cycle
    # Backward-compatible flag: image files are no longer generated here because
    # the Telegram review step must approve the exact card text first.

    candidates = get_top_topics(n=topics_limit + 10, settings=settings)
    draft_ids: list[int] = []
    skipped = 0
    considered = 0
    for story in candidates:
        if len(draft_ids) >= topics_limit:
            break
        considered += 1
        if store.is_seen(settings, story.object_id):
            skipped += 1
            continue
        draft_set = writer.draft_from_story(story, settings=settings, provider=provider)
        draft_id = store.create_draft(settings, story, draft_set)
        store.mark_seen(settings, story)
        draft_ids.append(draft_id)

    return CycleResult(draft_ids=draft_ids, skipped_seen=skipped, considered=considered)


def render_review_text(record: store.DraftRecord) -> str:
    """The human-facing review message (plan §5 template)."""
    angle = record.current_angle
    lines = [
        f"🔥 Topic: {record.topic_title}",
        f"   Why it's hot: {record.topic_why_hot}",
        f"   Source: {record.topic_url}",
        "",
        f"📝 Draft (angle: {angle.angle_type.label}) — {record.current_idx + 1}/"
        f"{len(record.draft_set.angles)}:",
        "",
        record.effective_text,
        "",
        "🖼 Image card text proposal:",
        f'"{image_card_text(record)}"',
        "",
        f"🖼 Image: {'attached' if record.image_path else 'not generated yet'}",
    ]
    if not record.image_path:
        lines.append('   Tap "Create image" only if the proposed card text is final.')
    if record.override_text:
        lines.append("✏️ (your edited version)")
    if angle.fact_flags and not record.override_text:
        lines.append("")
        lines.append("⚠️ Verify before posting:")
        for f in angle.fact_flags:
            lines.append(f"   • {f.claim}" + (f" — {f.reason}" if f.reason else ""))
    return "\n".join(lines)


def regenerate_current_angle(
    settings: Settings, record: store.DraftRecord, *, provider: LLMProvider | None = None
) -> None:
    """Re-roll the current angle in place and persist the new angle set."""
    new_angle = writer.regenerate_angle(
        title=record.topic_title,
        why_hot=record.topic_why_hot,
        url=record.topic_url,
        discussion_url=record.topic_url,
        angle_type=record.current_angle.angle_type,
        settings=settings,
        provider=provider,
    )
    draft_set = record.draft_set
    draft_set.angles[record.current_idx % len(draft_set.angles)] = new_angle
    store.set_angles_json(settings, record.id, draft_set.to_json())


def cycle_angle(settings: Settings, record: store.DraftRecord) -> int:
    new_idx = (record.current_idx + 1) % len(record.draft_set.angles)
    store.set_current_idx(settings, record.id, new_idx)
    return new_idx


def regenerate_image(settings: Settings, record: store.DraftRecord) -> str:
    path = images.make_card_for_draft(image_card_text(record), settings.image_dir, record.id)
    store.set_image(settings, record.id, path)
    return path


@dataclass
class PublishOutcome:
    post_urn: str
    over_cap: bool


def publish_draft(settings: Settings, draft_id: int, *, enforce_cap: bool = True) -> PublishOutcome:
    """Post the draft's effective text (+image) to LinkedIn and log it."""
    from linkedin_agent.linkedin import client

    record = store.get_draft(settings, draft_id)
    if record is None:
        raise RuntimeError(f"Draft {draft_id} not found.")

    over_cap = enforce_cap and store.posts_in_last_days(settings, 7) >= settings.max_posts_per_week
    text = record.effective_text
    if record.image_path:
        result = client.post_image(
            text, record.image_path, alt_text=record.current_angle.hook, settings=settings
        )
    else:
        result = client.post_text(text, settings=settings)

    store.record_post(settings, draft_id, result.post_urn, text, record.image_path)
    if record.topic_object_id:
        store.mark_topic_posted(settings, record.topic_object_id)
    # Learn from this post: the final text is a gold voice example, and if it was
    # edited, the AI-draft→final diff teaches the model what to change.
    feedback.record_finalization(settings, record)
    return PublishOutcome(post_urn=result.post_urn, over_cap=over_cap)
