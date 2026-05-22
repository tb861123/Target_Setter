"""SQLite session persistence for Target Setting Tool."""

from __future__ import annotations

import json
import pickle
import sqlite3
import time
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "target_setting.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                state BLOB NOT NULL
            )
        """)
        conn.commit()


def save_session(name: str, mode: str, state: dict) -> int:
    """Save or update a named session. Returns row id."""
    now = datetime.now().isoformat(timespec="seconds")
    blob = pickle.dumps(state)
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM sessions WHERE name = ? AND mode = ?", (name, mode)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessions SET state = ?, updated_at = ? WHERE id = ?",
                (blob, now, existing["id"]),
            )
            return existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO sessions (name, mode, created_at, updated_at, state) VALUES (?,?,?,?,?)",
                (name, mode, now, now, blob),
            )
            return cur.lastrowid


def load_session(session_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT state FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if row:
        return pickle.loads(row["state"])
    return None


def list_sessions(mode: str | None = None) -> list[dict]:
    with _connect() as conn:
        if mode:
            rows = conn.execute(
                "SELECT id, name, mode, created_at, updated_at FROM sessions WHERE mode = ? ORDER BY updated_at DESC",
                (mode,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, mode, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()


def get_most_recent_session(mode: str) -> dict | None:
    sessions = list_sessions(mode)
    if sessions:
        return sessions[0]
    return None
