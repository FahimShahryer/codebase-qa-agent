"""SQLite-backed cache for embeddings and LLM summaries.

Keyed on (content_hash, provider, model) so different providers/models can
coexist without collisions. Cache survives container restarts via the
./cache:/app/cache volume mount.
"""
from __future__ import annotations

import hashlib
import pickle
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

CACHE_DB_PATH = Path("/app/cache/cache.db")


def content_hash(text: str) -> str:
    """Stable SHA-256 hex digest of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Internal ─────────────────────────────────────────────────────────
@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH, timeout=10.0)
    try:
        yield conn
    finally:
        conn.close()


_INIT_SQL = """
CREATE TABLE IF NOT EXISTS embed_cache (
    content_hash TEXT NOT NULL,
    provider     TEXT NOT NULL,
    model        TEXT NOT NULL,
    dimension    INTEGER NOT NULL,
    vector       BLOB NOT NULL,
    created_at   REAL NOT NULL,
    PRIMARY KEY (content_hash, provider, model)
);

CREATE TABLE IF NOT EXISTS summary_cache (
    content_hash TEXT NOT NULL,
    provider     TEXT NOT NULL,
    model        TEXT NOT NULL,
    summary      TEXT NOT NULL,
    created_at   REAL NOT NULL,
    PRIMARY KEY (content_hash, provider, model)
);
"""


def init_cache() -> None:
    """Idempotent — safe to call on every startup."""
    with _conn() as conn:
        conn.executescript(_INIT_SQL)
        conn.commit()


# ── Embeddings ───────────────────────────────────────────────────────
def get_embedding(h: str, provider: str, model: str) -> list[float] | None:
    init_cache()
    with _conn() as conn:
        row = conn.execute(
            "SELECT vector FROM embed_cache WHERE content_hash=? AND provider=? AND model=?",
            (h, provider, model),
        ).fetchone()
    return pickle.loads(row[0]) if row else None


def set_embedding(h: str, provider: str, model: str, vector: list[float]) -> None:
    init_cache()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO embed_cache "
            "(content_hash, provider, model, dimension, vector, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (h, provider, model, len(vector), pickle.dumps(vector), time.time()),
        )
        conn.commit()


# ── Summaries ────────────────────────────────────────────────────────
def get_summary(h: str, provider: str, model: str) -> str | None:
    init_cache()
    with _conn() as conn:
        row = conn.execute(
            "SELECT summary FROM summary_cache WHERE content_hash=? AND provider=? AND model=?",
            (h, provider, model),
        ).fetchone()
    return row[0] if row else None


def set_summary(h: str, provider: str, model: str, summary: str) -> None:
    init_cache()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO summary_cache "
            "(content_hash, provider, model, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (h, provider, model, summary, time.time()),
        )
        conn.commit()


# ── Stats ────────────────────────────────────────────────────────────
def cache_stats() -> dict:
    init_cache()
    with _conn() as conn:
        e_total = conn.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0]
        s_total = conn.execute("SELECT COUNT(*) FROM summary_cache").fetchone()[0]
        e_by = dict(conn.execute(
            "SELECT provider || '/' || model, COUNT(*) FROM embed_cache GROUP BY provider, model"
        ).fetchall())
        s_by = dict(conn.execute(
            "SELECT provider || '/' || model, COUNT(*) FROM summary_cache GROUP BY provider, model"
        ).fetchall())
    return {
        "embeddings": {"total": e_total, "by_provider_model": e_by},
        "summaries": {"total": s_total, "by_provider_model": s_by},
    }
