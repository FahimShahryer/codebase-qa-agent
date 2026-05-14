"""GET /search — direct retrieval pipeline (dev-only).

Exposes the Step 6 hybrid+rerank+expand pipeline as an HTTP endpoint without
going through the agent loop. Used by:
- eval scripts (Step 10) for Recall@k / MRR measurement
- BM25 / rerank threshold tuning
- frontend debugging

Not exposed to the agent — agents use search_code via the tool layer.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import settings
from src.retrieve import search_code as _search

router = APIRouter()


class SearchHit(BaseModel):
    chunk_id: str
    chunk_type: str
    symbol_path: str
    symbol_name: str
    file_path: str
    start_line: int
    end_line: int
    summary: str
    hybrid_score: float
    rerank_score: float | None
    source: str       # "search" | "parent" | "callee" | "file"


@router.get("/search")
async def search(
    q: str,
    repo: str | None = None,
    k: int = 5,
    expand: bool = True,
) -> list[SearchHit]:
    """Run the 7-stage retrieval pipeline directly. dev-only."""
    if not q:
        raise HTTPException(400, "missing required query parameter 'q'")
    k = max(1, min(k, 20))

    tenant = (repo or settings.REPO_NAME).strip()
    if not tenant:
        raise HTTPException(400, "no repo configured")

    try:
        chunks = _search(q, tenant=tenant, top_k=k, expand=expand)
    except Exception as e:
        raise HTTPException(500, f"search failed: {e!s}")

    return [
        SearchHit(
            chunk_id=c.chunk_id,
            chunk_type=c.chunk_type,
            symbol_path=c.symbol_path,
            symbol_name=c.symbol_name,
            file_path=c.file_path,
            start_line=c.start_line,
            end_line=c.end_line,
            summary=c.summary,
            hybrid_score=c.hybrid_score,
            rerank_score=c.rerank_score,
            source=c.source,
        )
        for c in chunks
    ]
