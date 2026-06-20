"""
OmniContext — SQLite storage with FTS5 full-text search.
Handles schema creation, CRUD for events and sessions,
and FTS index maintenance.
"""

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from config import DB_PATH
from storage.models import Event, Session

logger = logging.getLogger(__name__)

_FTS_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


# ── Schema ──────────────────────────────────────────────────────────────────

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    start_time  TEXT NOT NULL,
    end_time    TEXT,
    topic       TEXT DEFAULT '',
    summary     TEXT DEFAULT '',
    event_count INTEGER DEFAULT 0
);
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    app_name        TEXT DEFAULT '',
    window_title    TEXT DEFAULT '',
    clipboard_text  TEXT DEFAULT '',
    screenshot_path TEXT DEFAULT '',
    ocr_text        TEXT DEFAULT '',
    summary         TEXT DEFAULT '',
    entities        TEXT DEFAULT '[]',
    topics          TEXT DEFAULT '[]',
    session_id      TEXT DEFAULT NULL,
    embedding_id    TEXT DEFAULT '',
    processed       INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""

_CREATE_EVENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    event_id UNINDEXED,
    window_title,
    ocr_text,
    summary,
    entities,
    topics
);
"""

_CREATE_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS events_fts_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, event_id, window_title, ocr_text, summary, entities, topics)
    VALUES (new.rowid, new.id, new.window_title, new.ocr_text, new.summary, new.entities, new.topics);
END;

CREATE TRIGGER IF NOT EXISTS events_fts_delete AFTER DELETE ON events BEGIN
    DELETE FROM events_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS events_fts_update AFTER UPDATE ON events BEGIN
    DELETE FROM events_fts WHERE rowid = old.rowid;
    INSERT INTO events_fts(rowid, event_id, window_title, ocr_text, summary, entities, topics)
    VALUES (new.rowid, new.id, new.window_title, new.ocr_text, new.summary, new.entities, new.topics);
END;
"""

_DROP_FTS_TRIGGERS = """
DROP TRIGGER IF EXISTS events_fts_insert;
DROP TRIGGER IF EXISTS events_fts_delete;
DROP TRIGGER IF EXISTS events_fts_update;
"""

_REBUILD_FTS = """
INSERT INTO events_fts(rowid, event_id, window_title, ocr_text, summary, entities, topics)
SELECT rowid, id, window_title, ocr_text, summary, entities, topics
FROM events;
"""


# ── Connection helper ────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_conn: Optional[sqlite3.Connection] = None
_db_lock = threading.RLock()


def get_db() -> sqlite3.Connection:
    """Return the module-level singleton connection."""
    global _conn
    with _db_lock:
        if _conn is None:
            _conn = _get_conn()
        return _conn


# ── Init ─────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables, indexes, and FTS if they don't exist."""
    with _db_lock:
        conn = get_db()
        with conn:
            conn.execute(_CREATE_SESSIONS)
            conn.execute(_CREATE_EVENTS)
            conn.execute(_CREATE_EVENTS_INDEX)
            conn.executescript(_DROP_FTS_TRIGGERS)
            conn.execute("DROP TABLE IF EXISTS events_fts")
            conn.execute(_CREATE_FTS)
            conn.execute(_REBUILD_FTS)
            # Triggers need to be created individually
            for stmt in _CREATE_FTS_TRIGGERS.strip().split("\nCREATE TRIGGER"):
                stmt = stmt.strip()
                if not stmt.startswith("CREATE"):
                    stmt = "CREATE TRIGGER " + stmt
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # Trigger already exists
    logger.info("Database initialised at %s", DB_PATH)


# ── Event helpers ────────────────────────────────────────────────────────────

def _row_to_event(row: sqlite3.Row) -> Event:
    d = dict(row)
    d["entities"] = json.loads(d.get("entities") or "[]")
    d["topics"] = json.loads(d.get("topics") or "[]")
    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
    d["processed"] = bool(d.get("processed", 0))
    d["session_id"] = d.get("session_id") or ""
    d["embedding_id"] = d.get("embedding_id") or ""
    return Event(**d)


def insert_event(event: Event) -> None:
    with _db_lock:
        conn = get_db()
        with conn:
            conn.execute(
                """
                INSERT INTO events
                (id, timestamp, app_name, window_title, clipboard_text,
                 screenshot_path, ocr_text, summary, entities, topics,
                 session_id, embedding_id, processed)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.id,
                    event.timestamp.isoformat(),
                    event.app_name,
                    event.window_title,
                    event.clipboard_text,
                    event.screenshot_path,
                    event.ocr_text,
                    event.summary,
                    json.dumps(event.entities),
                    json.dumps(event.topics),
                    event.session_id or None,
                    event.embedding_id,
                    int(event.processed),
                ),
            )


def update_event_ai_fields(
    event_id: str,
    ocr_text: str,
    summary: str,
    entities: List[str],
    topics: List[str],
    embedding_id: str,
) -> None:
    """Called after AI pipeline runs to patch an event in-place."""
    with _db_lock:
        conn = get_db()
        with conn:
            conn.execute(
                """
                UPDATE events
                SET ocr_text=?, summary=?, entities=?, topics=?,
                    embedding_id=?, processed=1
                WHERE id=?
                """,
                (
                    ocr_text,
                    summary,
                    json.dumps(entities),
                    json.dumps(topics),
                    embedding_id,
                    event_id,
                ),
            )


def get_event(event_id: str) -> Optional[Event]:
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return _row_to_event(row) if row else None


def delete_event(event_id: str) -> None:
    with _db_lock:
        conn = get_db()
        with conn:
            conn.execute("DELETE FROM events WHERE id=?", (event_id,))


def get_events(
    limit: int = 50,
    offset: int = 0,
    session_id: Optional[str] = None,
) -> List[Event]:
    with _db_lock:
        conn = get_db()
        if session_id:
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id=? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (session_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_to_event(r) for r in rows]


def get_unprocessed_events(limit: int = 20) -> List[Event]:
    with _db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM events WHERE processed=0 ORDER BY timestamp ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_event(r) for r in rows]


def count_events() -> int:
    with _db_lock:
        conn = get_db()
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def count_unprocessed() -> int:
    with _db_lock:
        conn = get_db()
        return conn.execute("SELECT COUNT(*) FROM events WHERE processed=0").fetchone()[0]


def fts_search(query: str, limit: int = 20) -> List[Tuple[str, float]]:
    """
    FTS5 keyword search.
    Returns list of (event_id, rank) ordered by relevance.
    FTS5 rank is negative; we negate it so higher = better.
    """
    terms = [term.replace('"', '""') for term in _FTS_TOKEN_RE.findall(query)]
    if not terms:
        return []
    match_query = " OR ".join(f'"{term}"' for term in terms[:12])

    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT event_id, rank
                FROM events_fts
                WHERE events_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
            return [(r["event_id"], -r["rank"]) for r in rows]
        except sqlite3.OperationalError as exc:
            logger.warning("FTS search error (query=%r): %s", query, exc)
            return []


# ── Session helpers ──────────────────────────────────────────────────────────

def _row_to_session(row: sqlite3.Row) -> Session:
    d = dict(row)
    d["start_time"] = datetime.fromisoformat(d["start_time"])
    if d.get("end_time"):
        d["end_time"] = datetime.fromisoformat(d["end_time"])
    return Session(**d)


def insert_session(session: Session) -> None:
    with _db_lock:
        conn = get_db()
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (id, start_time, end_time, topic, summary, event_count)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    session.id,
                    session.start_time.isoformat(),
                    session.end_time.isoformat() if session.end_time else None,
                    session.topic,
                    session.summary,
                    session.event_count,
                ),
            )


def update_session(session: Session) -> None:
    with _db_lock:
        conn = get_db()
        with conn:
            conn.execute(
                """
                UPDATE sessions
                SET end_time=?, topic=?, summary=?, event_count=?
                WHERE id=?
                """,
                (
                    session.end_time.isoformat() if session.end_time else None,
                    session.topic,
                    session.summary,
                    session.event_count,
                    session.id,
                ),
            )


def get_sessions(limit: int = 50, offset: int = 0) -> List[Session]:
    with _db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_session(r) for r in rows]


def count_sessions() -> int:
    with _db_lock:
        conn = get_db()
        return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def close_db() -> None:
    global _conn
    with _db_lock:
        if _conn:
            _conn.close()
            _conn = None
    logger.info("Database connection closed.")
