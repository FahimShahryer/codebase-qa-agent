"""GET/POST /repos endpoints — repo discovery + indexing trigger.

Sources of truth:
- Weaviate tenants (one tenant per repo) → repo existence + chunk_count
- /app/memory/repo_state.json sidecar → last_indexed_at metadata
- In-process _indexing_jobs dict → current indexing state (not persistent)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from src.config import settings
from src.store import count_chunks, list_tenants, weaviate_client

router = APIRouter()

REPOS_ROOT = Path("/app/repos")
REPO_STATE_PATH = Path("/app/memory/repo_state.json")

# In-process state for currently-running indexing jobs (not persisted —
# acceptable since indexing is a one-time operation per repo)
_indexing_jobs: dict[str, dict] = {}


class RepoInfo(BaseModel):
    name: str
    indexed: bool
    chunk_count: int
    last_indexed_at: str | None = None
    state: Literal["ready", "indexing", "not_indexed", "error"] = "ready"
    progress: float = 1.0


def _read_repo_state() -> dict:
    if REPO_STATE_PATH.exists():
        try:
            return json.loads(REPO_STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _write_repo_state(state: dict) -> None:
    REPO_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPO_STATE_PATH.write_text(json.dumps(state, indent=2))


def _build_repo_info(tenant: str, client) -> RepoInfo:
    try:
        count = count_chunks(client, tenant)
    except Exception:
        count = 0
    meta = _read_repo_state().get(tenant, {})
    job = _indexing_jobs.get(tenant)
    state: Literal["ready", "indexing", "not_indexed", "error"]
    progress: float
    if job:
        state = job["state"]
        progress = float(job.get("progress", 0.0))
    elif count == 0:
        state = "not_indexed"
        progress = 0.0
    else:
        state = "ready"
        progress = 1.0
    return RepoInfo(
        name=tenant,
        indexed=count > 0,
        chunk_count=count,
        last_indexed_at=meta.get("last_indexed_at"),
        state=state,
        progress=progress,
    )


@router.get("/repos")
async def list_repos() -> list[RepoInfo]:
    """List indexed repos with their status + chunk counts."""
    with weaviate_client() as client:
        try:
            tenants = list_tenants(client)
        except Exception:
            tenants = []
        return [_build_repo_info(t, client) for t in tenants]


@router.get("/repos/{repo}/status")
async def repo_status(repo: str) -> RepoInfo:
    """Status for a single repo (used by the frontend repo selector badge)."""
    with weaviate_client() as client:
        try:
            tenants = list_tenants(client)
        except Exception:
            tenants = []
        if repo not in tenants and repo not in _indexing_jobs:
            # Repo isn't indexed yet but may have source on disk
            src = REPOS_ROOT / repo
            return RepoInfo(
                name=repo,
                indexed=False,
                chunk_count=0,
                state="not_indexed" if src.is_dir() else "error",
                progress=0.0,
            )
        return _build_repo_info(repo, client)


@router.post("/repos/{repo}/index")
async def trigger_index(repo: str, bg: BackgroundTasks) -> dict:
    """Kick off an async indexing job for `repo`. Returns immediately."""
    src = REPOS_ROOT / repo
    if not src.is_dir():
        raise HTTPException(
            404, f"Repo source not found at /app/repos/{repo} — clone it first"
        )

    if repo in _indexing_jobs and _indexing_jobs[repo]["state"] == "indexing":
        return {"job_id": repo, "status": "already_running"}

    _indexing_jobs[repo] = {"state": "indexing", "progress": 0.0}
    bg.add_task(_run_indexing, repo)
    return {"job_id": repo, "status": "started"}


def _run_indexing(repo: str) -> None:
    """Worker function. Updates _indexing_jobs and the sidecar state file."""
    from src.index import index_repo  # heavy import, defer to worker
    try:
        stats = index_repo(REPOS_ROOT / repo, tenant=repo, progress=False)
        _indexing_jobs[repo] = {"state": "ready", "progress": 1.0}
        state = _read_repo_state()
        state[repo] = {
            "last_indexed_at": datetime.now(timezone.utc).isoformat(),
            "chunk_count": stats["final_count"],
        }
        _write_repo_state(state)
    except Exception as e:
        _indexing_jobs[repo] = {
            "state": "error",
            "progress": 0.0,
            "error": str(e),
        }
