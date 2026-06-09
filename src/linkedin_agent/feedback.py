"""Voice-learning loop.

Every published post is a real example of Amir's voice; every edit is a signal
about what the model gets wrong. We capture both at finalization and feed the
most recent ones back into the draft-writer prompt, so drafts drift toward his
voice the more he uses the tool.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from linkedin_agent.config import Settings
from linkedin_agent.db import connect

if TYPE_CHECKING:
    from linkedin_agent.store import DraftRecord


@dataclass
class EditPair:
    ai_draft: str
    final_text: str


def _upsert(settings: Settings, record: "DraftRecord", ai_draft: str,
           final_text: str, was_edited: bool) -> None:
    """One learned row per draft (latest interaction wins). DELETE+INSERT keeps
    created_at fresh so recency reflects your most recent touch on it."""
    with connect(settings.db_path) as conn:
        conn.execute("DELETE FROM learned_voice WHERE draft_id = ?", (record.id,))
        conn.execute(
            """INSERT INTO learned_voice
               (draft_id, topic_title, angle_type, ai_draft, final_text,
                was_edited, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (record.id, record.topic_title, record.current_angle.angle_type.value,
             ai_draft, final_text, int(was_edited), int(time.time())),
        )


def record_edit(settings: Settings, record: "DraftRecord") -> None:
    """Capture an edit the moment it's made (independent of posting), so the
    model learns your corrections even when nothing is published."""
    ai_draft = record.current_angle.full_text
    final_text = record.effective_text
    if not record.override_text or final_text.strip() == ai_draft.strip():
        return
    _upsert(settings, record, ai_draft, final_text, was_edited=True)


def record_finalization(settings: Settings, record: "DraftRecord") -> None:
    """Store a finalized post as a learned example. Called on publish.

    `was_edited` is true only when the user's version differs from the model's
    draft. Pure approvals still teach voice, but aren't counted as corrections.
    Upserts, so an edit captured earlier isn't double-counted on publish.
    """
    ai_draft = record.current_angle.full_text
    final_text = record.effective_text
    was_edited = bool(record.override_text) and final_text.strip() != ai_draft.strip()
    _upsert(settings, record, ai_draft, final_text, was_edited)


def recent_finals(settings: Settings, *, limit: int = 6) -> list[str]:
    """Most recent published posts (your voice), newest first, de-duplicated."""
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT final_text FROM learned_voice ORDER BY created_at DESC LIMIT ?",
            (limit * 2,),
        ).fetchall()
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        text = (r["final_text"] or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= limit:
            break
    return out


def recent_edits(settings: Settings, *, limit: int = 3) -> list[EditPair]:
    """Most recent (AI draft → your final) correction pairs, newest first."""
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT ai_draft, final_text FROM learned_voice "
            "WHERE was_edited = 1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [EditPair(ai_draft=r["ai_draft"] or "", final_text=r["final_text"] or "") for r in rows]


def stats(settings: Settings) -> dict:
    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(was_edited), 0) AS edited "
            "FROM learned_voice"
        ).fetchone()
    return {"total": row["total"], "edited": row["edited"]}
