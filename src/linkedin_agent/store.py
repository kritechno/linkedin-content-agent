"""DB-backed persistence for seen topics, the draft queue, and the post log."""

from __future__ import annotations

import time
from dataclasses import dataclass

from linkedin_agent.config import Settings
from linkedin_agent.db import connect
from linkedin_agent.draft.models import DraftSet
from linkedin_agent.research.models import Story


# ── seen topics (dedupe) ──────────────────────────────────────────────────
def is_seen(settings: Settings, object_id: str, *, within_days: int | None = None) -> bool:
    within_days = settings.topic_memory_days if within_days is None else within_days
    cutoff = int(time.time() - within_days * 86400)
    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_topics WHERE object_id = ? AND first_seen_at >= ?",
            (object_id, cutoff),
        ).fetchone()
    return row is not None


def mark_seen(settings: Settings, story: Story) -> None:
    with connect(settings.db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_topics (object_id, title, url, first_seen_at) "
            "VALUES (?, ?, ?, ?)",
            (story.object_id, story.title, story.url, int(time.time())),
        )


def mark_topic_posted(settings: Settings, object_id: str) -> None:
    with connect(settings.db_path) as conn:
        conn.execute("UPDATE seen_topics SET posted = 1 WHERE object_id = ?", (object_id,))


# ── draft queue ───────────────────────────────────────────────────────────
@dataclass
class DraftRecord:
    id: int
    topic_object_id: str
    topic_title: str
    topic_url: str
    topic_why_hot: str
    angles_json: str
    current_idx: int
    override_text: str | None
    image_path: str | None
    image_text: str | None
    status: str
    telegram_message_id: int | None
    post_urn: str | None

    @property
    def draft_set(self) -> DraftSet:
        return DraftSet.from_json(self.angles_json)

    @property
    def current_angle(self):
        angles = self.draft_set.angles
        return angles[self.current_idx % len(angles)]

    @property
    def effective_text(self) -> str:
        """What would actually be posted: a manual edit wins, else the current angle."""
        if self.override_text:
            return self.override_text
        return self.current_angle.full_text


def _row_to_record(row) -> DraftRecord:
    return DraftRecord(
        id=row["id"],
        topic_object_id=row["topic_object_id"],
        topic_title=row["topic_title"],
        topic_url=row["topic_url"],
        topic_why_hot=row["topic_why_hot"],
        angles_json=row["angles_json"],
        current_idx=row["current_idx"],
        override_text=row["override_text"],
        image_path=row["image_path"],
        image_text=row["image_text"],
        status=row["status"],
        telegram_message_id=row["telegram_message_id"],
        post_urn=row["post_urn"],
    )


def create_draft(settings: Settings, story: Story, draft_set: DraftSet) -> int:
    now = int(time.time())
    with connect(settings.db_path) as conn:
        cur = conn.execute(
            """INSERT INTO drafts
               (topic_object_id, topic_title, topic_url, topic_why_hot,
                angles_json, current_idx, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, 'pending', ?, ?)""",
            (story.object_id, story.title, story.url, draft_set.why_hot,
             draft_set.to_json(), now, now),
        )
        return cur.lastrowid


def get_draft(settings: Settings, draft_id: int) -> DraftRecord | None:
    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    return _row_to_record(row) if row else None


def _update(settings: Settings, draft_id: int, **fields) -> None:
    fields["updated_at"] = int(time.time())
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect(settings.db_path) as conn:
        conn.execute(f"UPDATE drafts SET {cols} WHERE id = ?", (*fields.values(), draft_id))


def set_status(settings: Settings, draft_id: int, status: str) -> None:
    _update(settings, draft_id, status=status)


def set_message_id(settings: Settings, draft_id: int, message_id: int) -> None:
    _update(settings, draft_id, telegram_message_id=message_id)


def set_current_idx(settings: Settings, draft_id: int, idx: int) -> None:
    _update(
        settings,
        draft_id,
        current_idx=idx,
        override_text=None,
        image_path=None,
        image_text=None,
    )


def set_override_text(settings: Settings, draft_id: int, text: str) -> None:
    _update(settings, draft_id, override_text=text, image_path=None, image_text=None)


def set_angles_json(settings: Settings, draft_id: int, angles_json: str) -> None:
    _update(
        settings,
        draft_id,
        angles_json=angles_json,
        override_text=None,
        image_path=None,
        image_text=None,
    )


def set_image(settings: Settings, draft_id: int, image_path: str | None) -> None:
    _update(settings, draft_id, image_path=image_path)


def set_image_text(settings: Settings, draft_id: int, text: str) -> None:
    """Set image-only text and clear any rendered image that used old text."""
    _update(settings, draft_id, image_text=text.strip(), image_path=None)


# ── post log ──────────────────────────────────────────────────────────────
def record_post(settings: Settings, draft_id: int, post_urn: str, text: str,
                image_path: str | None = None) -> None:
    now = int(time.time())
    with connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO post_log (draft_id, post_urn, text, image_path, posted_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (draft_id, post_urn, text, image_path, now),
        )
        conn.execute("UPDATE drafts SET status='posted', post_urn=? WHERE id=?",
                     (post_urn, draft_id))


def posts_in_last_days(settings: Settings, days: int = 7) -> int:
    cutoff = int(time.time() - days * 86400)
    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM post_log WHERE posted_at >= ?", (cutoff,)
        ).fetchone()
    return row["n"]
