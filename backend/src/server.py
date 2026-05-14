"""FastAPI app — composes lifespan-managed agent, exception handler, and routes."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.routes import chat, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the agent (with AsyncSqliteSaver) once at startup, reuse per request.

    The agent itself is stateless — per-thread state lives in the checkpointer
    keyed by `thread_id`, so a single shared agent serves many concurrent
    sessions safely.
    """
    from src.agent import build_agent  # lazy import: heavy LangChain deps
    async with build_agent() as agent:
        app.state.agent = agent
        yield
    # AsyncSqliteSaver.__aexit__ closes the SQLite connection cleanly


app = FastAPI(
    title="Codebase Q&A Agent",
    version="0.1.0",
    description="Agentic Q&A over a public GitHub codebase",
    lifespan=lifespan,
)


# ── Exception handler — never leak a stack trace to the client ───────
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "type": exc.__class__.__name__,
        },
    )


# ── Routes ───────────────────────────────────────────────────────────
# Step 1: /health
# Step 8: POST /chat (SSE)
# Step 9: /repos, /sessions, /files, /search
app.include_router(health.router)
app.include_router(chat.router)
