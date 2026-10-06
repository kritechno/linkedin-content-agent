"""Persistence layer — seen topics, draft queue, post log (temp DB)."""

from __future__ import annotations

import time

from linkedin_agent import store
from linkedin_agent.db import connect
from linkedin_agent.draft.llm import MockProvider
from linkedin_agent.draft import writer
from linkedin_agent.research.models import Story


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

    store.set_image_text(settings, draft_id, "image-only headline")
    rec = store.get_draft(settings, draft_id)
    assert rec.image_text == "image-only headline"

    # switching angle clears stale text/image overrides
    store.set_current_idx(settings, draft_id, 2)
    rec = store.get_draft(settings, draft_id)
    assert rec.override_text is None
    assert rec.image_text is None


def test_record_post_and_weekly_count(settings, story):
    ds = _make_draftset(story, settings)
    draft_id = store.create_draft(settings, story, ds)
    assert store.posts_in_last_days(settings, 7) == 0
    store.record_post(settings, draft_id, "urn:li:share:1", "posted text")
    rec = store.get_draft(settings, draft_id)
    assert rec.status == "posted"
    assert rec.post_urn == "urn:li:share:1"
    assert store.posts_in_last_days(settings, 7) == 1


# ── performance feedback loop ───────────────────────────────────────────────
def _publish(settings, object_id, text):
    s = Story(object_id=object_id, title=f"t-{object_id}", url="https://e.com",
              points=1, num_comments=1, author="a", created_at_i=int(time.time()))
    ds = _make_draftset(s, settings)
    did = store.create_draft(settings, s, ds)
    store.record_post(settings, did, f"urn:{object_id}", text)
    return did


def test_record_metrics_and_engagement_score(settings, story):
    ds = _make_draftset(story, settings)
    did = store.create_draft(settings, story, ds)
    store.record_post(settings, did, "urn:x", "hello")

    [p] = store.list_recent_posts(settings)
    assert p.has_metrics is False and p.draft_id == did

    assert store.record_metrics(
        settings, did, impressions=500, reactions=20, comments=3, reposts=1
    ) is True
    [p] = store.list_recent_posts(settings)
    assert p.has_metrics is True
    assert p.impressions == 500
    assert p.engagement_score == 20 + 2 * 3 + 3 * 1  # reactions + 2*comments + 3*reposts


def test_record_metrics_unknown_draft_returns_false(settings):
    assert store.record_metrics(settings, 9999, reactions=5) is False


def test_top_performing_orders_by_engagement(settings):
    low = _publish(settings, "201", "low post")
    mid = _publish(settings, "202", "mid post")
    high = _publish(settings, "203", "high post")
    store.record_metrics(settings, low, reactions=10)                 # score 10
    store.record_metrics(settings, mid, reactions=5, comments=10)     # score 25
    store.record_metrics(settings, high, reactions=1, reposts=10)     # score 31

    top = store.top_performing_posts(settings, limit=2)
    assert top == ["high post", "mid post"]  # best first, low cut by limit


def test_top_performing_excludes_unmeasured_posts(settings):
    _publish(settings, "301", "no metrics post")
    measured = _publish(settings, "302", "measured post")
    store.record_metrics(settings, measured, reactions=4)
    assert store.top_performing_posts(settings) == ["measured post"]


def test_posts_needing_metrics_age_window(settings):
    did = _publish(settings, "401", "needs metrics")
    # Freshly posted → too new for the [3,6]-day nudge window.
    assert store.posts_needing_metrics(settings) == []

    with connect(settings.db_path) as conn:
        conn.execute("UPDATE post_log SET posted_at = ? WHERE draft_id = ?",
                     (int(time.time()) - 4 * 86400, did))
    pending = store.posts_needing_metrics(settings)
    assert len(pending) == 1 and pending[0].draft_id == did

    store.record_metrics(settings, did, reactions=1)  # once recorded, drops out
    assert store.posts_needing_metrics(settings) == []
