"""SQLite storage. Holds OAuth tokens now; seen-topics / post-log land later."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider              TEXT PRIMARY KEY,
    access_token          TEXT NOT NULL,
    refresh_token         TEXT,
    access_expires_at     INTEGER NOT NULL,   -- unix seconds
    refresh_expires_at    INTEGER,            -- unix seconds
    scope                 TEXT,
    member_urn            TEXT,               -- urn:li:person:{sub}
    updated_at            INTEGER NOT NULL
);

-- Topics we've already surfaced, so we don't repeat stories (plan §9).
CREATE TABLE IF NOT EXISTS seen_topics (
    object_id       TEXT PRIMARY KEY,         -- HN objectID
    title           TEXT NOT NULL,
    url             TEXT,
    first_seen_at   INTEGER NOT NULL,         -- unix seconds
    posted          INTEGER NOT NULL DEFAULT 0
);

-- The review queue. Holds the full generated angle set as JSON so "other
-- angle" can switch without another LLM call.
CREATE TABLE IF NOT EXISTS drafts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_object_id     TEXT,
    topic_title         TEXT,
    topic_url           TEXT,
    topic_why_hot       TEXT,
    angles_json         TEXT NOT NULL,        -- serialized DraftSet
    current_idx         INTEGER NOT NULL DEFAULT 0,
    override_text       TEXT,                 -- set when the user edits manually
    image_path          TEXT,
    image_text          TEXT,                 -- optional image-only text override
    status              TEXT NOT NULL DEFAULT 'pending',
    telegram_message_id INTEGER,
    post_urn            TEXT,
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL
);

-- Append-only log of everything actually published. The metrics_* columns are
-- filled in later (manually, via /perf in Telegram) to close the performance
-- feedback loop: which posts actually landed → feed the winners back into drafts.
CREATE TABLE IF NOT EXISTS post_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id           INTEGER,
    post_urn           TEXT,
    text               TEXT,
    image_path         TEXT,
    posted_at          INTEGER NOT NULL,
    impressions        INTEGER,
    reactions          INTEGER,
    comments           INTEGER,
    reposts            INTEGER,
    metrics_updated_at INTEGER          -- when performance numbers were last set
);

-- Voice-learning corpus: every finalized post becomes a gold voice example,
-- and edits keep the AI draft alongside the final so the model can learn the
-- corrections you make. Fed back into the draft-writer prompt over time.
CREATE TABLE IF NOT EXISTS learned_voice (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id     INTEGER,
    topic_title  TEXT,
    angle_type   TEXT,
    ai_draft     TEXT,          -- the model's original text for the chosen angle
    final_text   TEXT NOT NULL, -- what was actually published (your version)
    was_edited   INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL
);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "drafts", "image_text", "TEXT")
        # Performance-feedback columns on pre-existing post_log tables.
        for col in ("impressions", "reactions", "comments", "reposts", "metrics_updated_at"):
            _ensure_column(conn, "post_log", col, "INTEGER")


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
