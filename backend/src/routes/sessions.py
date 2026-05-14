"""/sessions endpoints — sidebar list, message-history reload, deletion.

Sessions metadata lives in /app/memory/sessions.db (separate from the
LangGraph checkpointer's memory.db to avoid sqlite contention between the
async checkpointer and sync metadata writes).

Conversation history itself is reconstructed via agent.aget_state(config) —
LangGraph's checkpointer holds the messages in graph state.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

SESSIONS_DB_PATH = Path("/app/memory/sessions.db")
CHECKPOINTER_DB_PATH = Path("/app/memory/memory.db")


class SessionInfo(BaseModel):
    id: str
    title: str
    repo: str
    created_at: str
    last_message_at: str
    message_count: int


class SessionMessage(BaseModel):
    role: str                   # "user" | "assistant" | "tool"
    content: str
    name: str | None = None     # tool name when role=="tool"
    tool_calls: list[dict] | None = None  # populated when role=="assistant"


# ── DB lifecycle ─────────────────────────────────────────────────────
def _init_sessions_db() -> None:
    SESSIONS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SESSIONS_DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                repo            TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                last_message_at TEXT NOT NULL,
                message_count   INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS sessions_last_message_idx
                ON sessions(last_message_at DESC);
            """
        )


@contextmanager
def _sessions_conn() -> Iterator[sqlite3.Connection]:
    _init_sessions_db()
    conn = sqlite3.connect(SESSIONS_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── Public upsert (called from /chat) ────────────────────────────────
def upsert_session(session_id: str, repo: str, message: str) -> None:
    """Increment message_count + bump last_message_at; create row on first turn."""
    now = datetime.now(timezone.utc).isoformat()
    title = message[:60] + ("..." if len(message) > 60 else "")
    with _sessions_conn() as conn:
        cur = conn.execute(
            "UPDATE sessions SET last_message_at=?, message_count=message_count+1 "
            "WHERE id=?",
            (now, session_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO sessions "
                "(id, title, repo, created_at, last_message_at, message_count) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (session_id, title, repo, now, now),
            )
        conn.commit()


# ── Routes ───────────────────────────────────────────────────────────
@router.get("/sessions")
async def list_sessions() -> list[SessionInfo]:
    """List past sessions, most-recent first."""
    with _sessions_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, repo, created_at, last_message_at, message_count "
            "FROM sessions ORDER BY last_message_at DESC"
        ).fetchall()
    return [SessionInfo(**dict(r)) for r in rows]


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, request: Request) -> list[SessionMessage]:
    """Reconstruct conversation from the LangGraph checkpointer's state."""
    agent = request.app.state.agent
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = await agent.aget_state(config)
    except Exception as e:
        raise HTTPException(500, f"State load error: {e!s}")

    if state is None or not getattr(state, "values", None):
        return []

    msgs: list[Any] = state.values.get("messages", []) or []
    out: list[SessionMessage] = []
    for m in msgs:
        cls = m.__class__.__name__
        content = m.content if isinstance(m.content, str) else str(m.content)
        if cls == "HumanMessage":
            out.append(SessionMessage(role="user", content=content))
        elif cls == "AIMessage":
            tool_calls = None
            if getattr(m, "tool_calls", None):
                tool_calls = [
                    {"name": tc.get("name"), "args": tc.get("args", {})}
                    for tc in m.tool_calls
                ]
            out.append(SessionMessage(
                role="assistant", content=content, tool_calls=tool_calls,
            ))
        elif cls == "ToolMessage":
            out.append(SessionMessage(
                role="tool",
                name=getattr(m, "name", None),
                content=content[:500],   # cap tool output payload
            ))
    return out


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Drop both the metadata row and the underlying checkpoints."""
    with _sessions_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM sessions WHERE id=?", (session_id,),
        ).rowcount
        conn.commit()

    # LangGraph has no public delete API for checkpoints — drop the rows
    # directly. Tables: checkpoints, writes, checkpoint_migrations.
    checkpoints_removed = 0
    if CHECKPOINTER_DB_PATH.exists():
        try:
            with sqlite3.connect(CHECKPOINTER_DB_PATH, timeout=5.0) as conn:
                cur = conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id=?", (session_id,),
                )
                checkpoints_removed = cur.rowcount
                conn.execute("DELETE FROM writes WHERE thread_id=?", (session_id,))
                conn.commit()
        except sqlite3.Error:
            pass

    if deleted == 0 and checkpoints_removed == 0:
        raise HTTPException(404, f"Session '{session_id}' not found")

    return {
        "deleted": session_id,
        "metadata_rows_removed": deleted,
        "checkpoint_rows_removed": checkpoints_removed,
    }
