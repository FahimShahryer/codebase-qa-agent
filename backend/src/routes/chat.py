"""POST /chat — streaming SSE chat endpoint.

Translates LangGraph's astream(stream_mode=["updates", "messages"]) into a
text/event-stream of typed SSE events that the Next.js frontend (Step 9)
consumes via Vercel AI SDK's `useChat({ onData })`.

verified: /langchain-ai/langgraph stream mode multi-tuple shape (mode, payload);
FastAPI StreamingResponse with text/event-stream media type (stable since 0.x).
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()


# ── Request shape ────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1,
                            description="Stable thread id — same value across "
                                        "follow-up turns to reuse memory.")
    repo: str | None = Field(default=None,
                             description="Tenant override (default: REPO_NAME).")
    message: str = Field(..., min_length=1, max_length=4000,
                         description="User's question.")


# ── Citation parser ──────────────────────────────────────────────────
# Tool outputs (see backend/src/tools.py:_format_chunk) start each chunk with
# a header line like:
#   [1] src/flask/app.py:967-990 (method: flask.app.Flask.dispatch_request)
# The agent is prompted to cite these as `[path:start-end]`; the frontend
# converts those markers into clickable links using the citations event.
_CITATION_RE = re.compile(
    r"^\[(\d+)\] ([^\s:]+):(\d+)-(\d+) \(([^:]+):\s*(.+?)\)\s*$",
    re.MULTILINE,
)


def _parse_citations(text: str) -> list[dict]:
    refs: list[dict] = []
    for m in _CITATION_RE.finditer(text):
        idx, path, start, end, kind, sym = m.groups()
        refs.append({
            "id": int(idx),
            "path": path.strip(),
            "start": int(start),
            "end": int(end),
            "kind": kind.strip(),
            "symbol": sym.strip(),
        })
    return refs


# ── SSE framer ───────────────────────────────────────────────────────
def _sse(event: str, data: dict) -> str:
    """Standard SSE frame: `event: NAME\\ndata: JSON\\n\\n`."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Endpoint ─────────────────────────────────────────────────────────
@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Stream agent events as Server-Sent Events.

    Emitted event types (in order):
      tool_start  — agent invoked a tool: { tool, args }
      tool_end    — tool returned: { tool, hits, preview }
      token       — incremental LLM token: { text }
      citations   — union of all chunk refs seen: { refs: [{...}, ...] }
      done        — terminal: {}
      error       — exception (mid-stream, terminal): { message, type }
    """
    agent = request.app.state.agent

    return StreamingResponse(
        _event_stream(agent, req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # disable nginx-style buffering
        },
    )


# ── Stream translator ────────────────────────────────────────────────
async def _event_stream(agent, req: ChatRequest) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": req.session_id}}
    seen_citations: dict[tuple, dict] = {}     # dedup by (path, start, end)

    try:
        async for mode, payload in agent.astream(
            {"messages": [{"role": "user", "content": req.message}]},
            config,
            stream_mode=["updates", "messages"],
        ):
            if mode == "updates":
                # payload shape: { node_name: { messages: [AIMessage|ToolMessage, ...] } }
                for _node_name, data in payload.items():
                    if not isinstance(data, dict):
                        continue
                    for msg in data.get("messages", []):
                        cls = msg.__class__.__name__

                        # Agent decided to invoke tool(s)
                        if cls == "AIMessage" and getattr(msg, "tool_calls", None):
                            for tc in msg.tool_calls:
                                yield _sse("tool_start", {
                                    "tool": tc.get("name", ""),
                                    "args": tc.get("args", {}),
                                })

                        # Tool returned its result
                        elif cls == "ToolMessage":
                            content = msg.content if isinstance(msg.content, str) else str(msg.content)
                            refs = _parse_citations(content)
                            for ref in refs:
                                key = (ref["path"], ref["start"], ref["end"])
                                if key not in seen_citations:
                                    seen_citations[key] = ref
                            yield _sse("tool_end", {
                                "tool": getattr(msg, "name", "unknown"),
                                "hits": len(refs),
                                "preview": content[:200],
                            })

            elif mode == "messages":
                # payload shape: (BaseMessageChunk, metadata_dict). The mode
                # streams every message chunk including tool outputs — filter
                # to AIMessage(Chunk) only so we don't echo tool result blobs
                # as `token` events (those are already announced via tool_end).
                chunk, _meta = payload
                cls = chunk.__class__.__name__
                if cls in ("AIMessageChunk", "AIMessage"):
                    text = getattr(chunk, "content", "") or ""
                    if text:
                        yield _sse("token", {"text": text})

    except Exception as e:  # noqa: BLE001 — agent errors must surface to client
        yield _sse("error", {
            "message": str(e),
            "type": e.__class__.__name__,
        })
        return

    yield _sse("citations", {"refs": list(seen_citations.values())})
    yield _sse("done", {})
