"""SQLite-backed store for users and API keys.

Each API key entitles its holder to register exactly one compute node.
Users must verify their email before they can generate API keys.
"""

from __future__ import annotations

import os
import sqlite3
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional


# Default DB path – overridden by tests via init_db(":memory:")
_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "janus.db")

# Module-level connection – set by init_db()
_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    """Return the current database connection, initialising if needed."""
    global _conn
    if _conn is None:
        init_db(_DEFAULT_DB_PATH)
    assert _conn is not None
    return _conn


def init_db(db_path: str = _DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    (Re)initialise the database connection and create tables.

    Pass `\":memory:\"` for an ephemeral in-memory database (used by tests).
    """
    global _conn
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              TEXT PRIMARY KEY,
            email           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            email_verified  INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key        TEXT PRIMARY KEY,
            user_id    TEXT,
            created_at TEXT NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0,
            node_id    TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    _conn.commit()
    return _conn


def close_db() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


# ── public helpers ────────────────────────────────────────────────────────────

def generate_api_key(user_id: str) -> dict:
    """Create a new API key for *user_id*, store it, and return its metadata."""
    key = f"janus_{secrets.token_urlsafe(32)}"
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO api_keys (key, user_id, created_at, used, node_id) VALUES (?, ?, ?, 0, NULL)",
        (key, user_id, now),
    )
    conn.commit()
    return {"key": key, "created_at": now, "used": False, "node_id": None}


def validate_api_key(key: str) -> dict:
    """
    Look up an API key and return its row as a dict.

    Raises:
        KeyError  – key does not exist
        ValueError – key has already been used
    """
    conn = get_conn()
    row = conn.execute("SELECT * FROM api_keys WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise KeyError("Invalid API key")
    if row["used"]:
        raise ValueError("API key has already been used to register a node")
    return dict(row)


def mark_key_used(key: str, node_id: str) -> None:
    """Mark an API key as consumed and link it to the created node."""
    conn = get_conn()
    conn.execute(
        "UPDATE api_keys SET used = 1, node_id = ? WHERE key = ?",
        (node_id, key),
    )
    conn.commit()


def get_api_key_info(key: str) -> Optional[dict]:
    """Return metadata for a key, or None if not found."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM api_keys WHERE key = ?", (key,)).fetchone()
    return dict(row) if row else None


# ── user helpers ──────────────────────────────────────────────────────────────

def create_user(email: str, password_hash: str) -> dict:
    """Insert a new user and return their record as a dict.

    Raises sqlite3.IntegrityError if the email already exists.
    """
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO users (id, email, password_hash, email_verified, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (user_id, email, password_hash, now),
    )
    conn.commit()
    return {
        "id": user_id,
        "email": email,
        "email_verified": False,
        "created_at": now,
    }


def get_user_by_email(email: str) -> Optional[dict]:
    """Return the user row for *email*, or None."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Return the user row for *user_id*, or None."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def verify_user_email(email: str) -> bool:
    """Mark a user's email as verified. Returns True if a row was updated."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE users SET email_verified = 1 WHERE email = ?", (email,)
    )
    conn.commit()
    return cur.rowcount > 0
