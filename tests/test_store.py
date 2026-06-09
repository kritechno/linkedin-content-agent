"""Persistence layer — seen topics, draft queue, post log (temp DB)."""

from __future__ import annotations

import time

from linkedin_agent import store
from linkedin_agent.db import connect
from linkedin_agent.draft.llm import MockProvider
from linkedin_agent.draft import writer


def _make_draftset(story, settings):
    return writer.generate_draft_set(
        title=story.title, why_hot="hot", url=story.url,
        discussion_url=story.discussion_url, settings=settings,
        provider=MockProvider(), ground=False,
    )


def test_seen_topics_dedupe(settings, story):
    assert store.is_seen(settings, story.object_id) is False
    store.mark_seen(settings, story)
    assert store.is_seen(settings, story.object_id) is True
    # Age the record past the 30-day memory horizon → it may resurface.
    with connect(settings.db_path) as conn:
        conn.execute(
            "UPDATE seen_topics SET first_seen_at = ? WHERE object_id = ?",
            (int(time.time()) - 40 * 86400, story.object_id),
        )
    assert store.is_seen(settings, story.object_id, within_days=30) is False


def test_create_and_get_draft(settings, story):
    ds = _make_draftset(story, settings)
    draft_id = store.create_draft(settings, story, ds)
    rec = store.get_draft(settings, draft_id)
    assert rec is not None
    assert rec.status == "pending"
    assert rec.current_idx == 0
    assert rec.effective_text == ds.angles[0].full_text


def test_cycle_angle_and_override(settings, story):
    ds = _make_draftset(story, settings)
    draft_id = store.create_draft(settings, story, ds)

    store.set_current_idx(settings, draft_id, 1)
    rec = store.get_draft(settings, draft_id)
    assert rec.current_idx == 1
    assert rec.effective_text == ds.angles[1].full_text

    store.set_override_text(settings, draft_id, "my hand-edited post")
    rec = store.get_draft(settings, draft_id)
    assert rec.effective_text == "my hand-edited post"

    # switching angle clears the override
    store.set_current_idx(settings, draft_id, 2)
    rec = store.get_draft(settings, draft_id)
    assert rec.override_text is None


def test_record_post_and_weekly_count(settings, story):
    ds = _make_draftset(story, settings)
    draft_id = store.create_draft(settings, story, ds)
    assert store.posts_in_last_days(settings, 7) == 0
    store.record_post(settings, draft_id, "urn:li:share:1", "posted text")
    rec = store.get_draft(settings, draft_id)
    assert rec.status == "posted"
    assert rec.post_urn == "urn:li:share:1"
    assert store.posts_in_last_days(settings, 7) == 1
