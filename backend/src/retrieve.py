"""7-stage retrieval pipeline — the heart of search_code.

Stages (per approach1.md Step 5):
  1. alpha auto-detect (regex)
  2. (optional) HyDE — flag, not wired by default
  3. hybrid search over-retrieve to limit*4
  4. cross-encoder rerank → top_k
  5. context expansion (parent class, top callees, file summary), capped at 6
  6. dedupe by chunk_id
  7. pack with [N] numbering — done by the caller / agent layer

verified:
- sentence-transformers CrossEncoder.predict (May 2026): accepts
  activation_fn=Sigmoid() for [0,1] normalized scores
- weaviate-python-client v4.21: Filter.by_property(...).equal | Filter
  combinators with `&` and `|`, query.hybrid with query_properties weights
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

import torch.nn
import weaviate
from weaviate.classes.query import Filter, MetadataQuery

from src.config import settings
from src.embed import Embedder
from src.store import COLLECTION_NAME, weaviate_client


# ── Constants ────────────────────────────────────────────────────────
# BM25 property weights (Step 4 design — identifier match outranks
# whole-body keyword frequency)
BM25_QUERY_PROPERTIES: list[str] = [
    "symbol_name^4",
    "symbol_tokens^3",
    "symbol_path^2.5",
    "summary^2",
    "docstring^2",
    "file_path^1.5",
    "code^1",
]

# Rerank input max chars — bge-reranker-base has 512-token context;
# ~3 chars/token in code gives us ~1500 chars total before truncation.
RERANK_INPUT_MAX = 1500

# Refusal threshold on sigmoid'd rerank scores (Step 6 design)
DEFAULT_REFUSAL_THRESHOLD = 0.3


# ── Data types ───────────────────────────────────────────────────────
@dataclass
class RetrievedChunk:
    """Hydrated chunk ready for the agent / answering LLM."""
    chunk_id: str
    chunk_type: str
    symbol_path: str
    symbol_name: str
    file_path: str
    start_line: int
    end_line: int
    code: str
    summary: str
    docstring: str
    imports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    is_test: bool = False
    parent_symbol: str = ""
    module_path: str = ""
    hybrid_score: float = 0.0
    rerank_score: float | None = None
    source: str = "search"  # "search" | "parent" | "callee" | "file"


# ── Stage 1: alpha auto-detect ───────────────────────────────────────
_CODE_TOKEN_RE = re.compile(
    # camelCase call,  dotted.method call,  ::,  ->,  snake_case identifier
    r"[A-Z_][a-zA-Z0-9_]*\(|\.[a-z_]+\(|::|->|\b[a-z]+_[a-z]+\b"
)


def detect_alpha(query: str) -> float:
    """0.4 for code-token queries (BM25-heavy), 0.75 for prose (vector-heavy)."""
    return 0.4 if _CODE_TOKEN_RE.search(query) else 0.75


# ── Reranker singleton (lazy load) ───────────────────────────────────
@lru_cache(maxsize=1)
def _get_reranker():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.RERANKER_MODEL)


_SIGMOID = torch.nn.Sigmoid()


# ── Helpers ──────────────────────────────────────────────────────────
def _row_to_chunk(obj, *, source: str = "search") -> RetrievedChunk:
    p = obj.properties
    score = 0.0
    if obj.metadata is not None and getattr(obj.metadata, "score", None) is not None:
        score = float(obj.metadata.score)
    return RetrievedChunk(
        chunk_id=str(obj.uuid),
        chunk_type=p.get("chunk_type", ""),
        symbol_path=p.get("symbol_path", "") or "",
        symbol_name=p.get("symbol_name", "") or "",
        file_path=p.get("file_path", "") or "",
        start_line=int(p.get("start_line") or 0),
        end_line=int(p.get("end_line") or 0),
        code=p.get("code_raw") or p.get("code") or "",
        summary=p.get("summary", "") or "",
        docstring=p.get("docstring", "") or "",
        imports=list(p.get("imports") or []),
        calls=list(p.get("calls") or []),
        decorators=list(p.get("decorators") or []),
        is_test=bool(p.get("is_test", False)),
        parent_symbol=p.get("parent_symbol", "") or "",
        module_path=p.get("module_path", "") or "",
        hybrid_score=score,
        source=source,
    )


def _rerank_text(c: RetrievedChunk) -> str:
    """Build the (query, doc) pair text for the cross-encoder.

    Summary > docstring > code, capped at RERANK_INPUT_MAX chars.
    """
    parts: list[str] = []
    if c.symbol_path:
        parts.append(c.symbol_path)
    if c.summary:
        parts.append(c.summary)
    if c.docstring:
        parts.append(c.docstring[:400])
    if c.code:
        parts.append(c.code[:800])
    return "\n".join(parts)[:RERANK_INPUT_MAX]


# ── Stage 3: hybrid search ───────────────────────────────────────────
def hybrid_search(
    client: weaviate.WeaviateClient,
    *,
    tenant: str,
    query: str,
    vector: list[float],
    alpha: float = 0.7,
    limit: int = 20,
    filters: Filter | None = None,
) -> list[RetrievedChunk]:
    coll = client.collections.use(COLLECTION_NAME).with_tenant(tenant)
    response = coll.query.hybrid(
        query=query,
        vector=vector,
        alpha=alpha,
        query_properties=BM25_QUERY_PROPERTIES,
        limit=limit,
        filters=filters,
        return_metadata=MetadataQuery(score=True, explain_score=True),
    )
    return [_row_to_chunk(o, source="search") for o in response.objects]


# ── Stage 4: cross-encoder rerank ────────────────────────────────────
def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    if not candidates:
        return []
    reranker = _get_reranker()
    pairs = [(query, _rerank_text(c)) for c in candidates]
    # Sigmoid → [0, 1] for consistent thresholding across queries
    raw = reranker.predict(pairs, activation_fn=_SIGMOID)
    for c, s in zip(candidates, raw):
        c.rerank_score = float(s)
    return sorted(candidates, key=lambda c: -(c.rerank_score or 0.0))[:top_k]


# ── Stage 5: context expansion ───────────────────────────────────────
def expand_context(
    client: weaviate.WeaviateClient,
    *,
    tenant: str,
    chunks: list[RetrievedChunk],
    max_extras: int = 6,
) -> list[RetrievedChunk]:
    """Pull in 1-hop neighbours: parent class, top callees, file summary."""
    if not chunks:
        return chunks
    extras: list[RetrievedChunk] = []
    seen: set[str] = {c.chunk_id for c in chunks}
    coll = client.collections.use(COLLECTION_NAME).with_tenant(tenant)

    def _add(obj_iter, source: str) -> None:
        for o in obj_iter:
            if len(extras) >= max_extras:
                return
            c = _row_to_chunk(o, source=source)
            if c.chunk_id in seen:
                continue
            extras.append(c)
            seen.add(c.chunk_id)

    # ── 5a. Parent expansion: for each method, fetch its class ──────
    for c in chunks:
        if len(extras) >= max_extras:
            break
        if c.chunk_type == "method" and c.parent_symbol:
            r = coll.query.fetch_objects(
                filters=(
                    Filter.by_property("file_path").equal(c.file_path)
                    & Filter.by_property("chunk_type").equal("class")
                    & Filter.by_property("symbol_name").equal(c.parent_symbol)
                ),
                limit=1,
            )
            _add(r.objects, "parent")

    # ── 5b. Callee expansion: top chunk's first 3 callees ──────────
    if chunks[0].calls and len(extras) < max_extras:
        for callee in chunks[0].calls[:3]:
            if len(extras) >= max_extras:
                break
            r = coll.query.fetch_objects(
                filters=(
                    Filter.by_property("symbol_name").equal(callee)
                    & (
                        Filter.by_property("chunk_type").equal("function")
                        | Filter.by_property("chunk_type").equal("method")
                    )
                ),
                limit=1,
            )
            _add(r.objects, "callee")

    # ── 5c. File summary: if >=2 chunks from same file, add file chunk ──
    file_counts = Counter(c.file_path for c in chunks)
    for path, count in file_counts.items():
        if len(extras) >= max_extras:
            break
        if count < 2:
            continue
        r = coll.query.fetch_objects(
            filters=(
                Filter.by_property("file_path").equal(path)
                & Filter.by_property("chunk_type").equal("file")
            ),
            limit=1,
        )
        _add(r.objects, "file")

    return chunks + extras


# ── Top-level: full 7-stage pipeline ─────────────────────────────────
def search_code(
    query: str,
    *,
    tenant: str | None = None,
    top_k: int = 5,
    over_retrieve: int = 20,
    expand: bool = True,
    filters: Filter | None = None,
    use_hyde: bool = False,  # stub; HyDE blending lands in Step 7+
) -> list[RetrievedChunk]:
    """End-to-end retrieval. Returns top-k reranked chunks (+ up to 6 expansions)."""
    tenant = tenant or settings.REPO_NAME
    embedder = Embedder()

    # Stage 1
    alpha = detect_alpha(query)

    # Stage 2 (deferred — HyDE blending TODO Step 7)
    vectors, _ = embedder.embed([query])
    query_vec = vectors[0]

    with weaviate_client() as client:
        # Stage 3: hybrid over-retrieve
        candidates = hybrid_search(
            client,
            tenant=tenant,
            query=query,
            vector=query_vec,
            alpha=alpha,
            limit=over_retrieve,
            filters=filters,
        )

        # Stage 4: rerank
        ranked = rerank(query, candidates, top_k=top_k)

        # Stage 5+6: expand + dedupe
        if expand:
            ranked = expand_context(client, tenant=tenant, chunks=ranked)

    return ranked


# ── Helper used by the agent / answering LLM in Step 7+ ──────────────
def should_answer(
    ranked: list[RetrievedChunk],
    *,
    threshold: float = DEFAULT_REFUSAL_THRESHOLD,
) -> bool:
    """Refusal gate. If top-1 rerank score < threshold, the agent should
    decline rather than hallucinate. Used in Step 7."""
    if not ranked:
        return False
    top_search = next((c for c in ranked if c.source == "search"), None)
    if top_search is None or top_search.rerank_score is None:
        return bool(ranked)
    return top_search.rerank_score >= threshold
