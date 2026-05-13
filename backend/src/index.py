"""Full indexing pipeline: discover → summarize → embed → upsert.

The orchestrator that wires Steps 1-4 together. Batches chunks, parallelises
summary generation (I/O-bound) with a thread pool, batch-embeds within each
group, and upserts to Weaviate with deterministic UUIDs.

verified: weaviate-python-client v4.21 (May 2026) — DataObject(properties=,
uuid=, vector=), collection.with_tenant().data.insert_many, idempotent
upsert via stable UUIDs.
"""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

from tqdm import tqdm
import weaviate
from weaviate.classes.data import DataObject

from src.chunks import Chunk
from src.embed import Embedder
from src.extract import extract_from_repo
from src.store import (
    COLLECTION_NAME,
    chunk_to_properties,
    chunk_uuid,
    count_chunks,
    drop_schema,
    ensure_tenant,
    init_schema,
    weaviate_client,
)
from src.summarize import Summarizer

# Tuning knobs
CHUNK_BATCH_SIZE = 32         # chunks processed per pipeline batch
SUMMARY_CONCURRENCY = 8       # parallel summary requests (OpenAI tier-1 friendly)
EMBED_TEXT_CODE_CAP = 1500    # max code chars in embed_text (cost cap)


# ── Embed-text builder (Strategy C: summary + context + code) ─────────
def build_embed_text(chunk: Chunk, summary: str) -> str:
    """Per-chunk-type recipe matching approach1.md Step 3.

    Pattern: natural-language framing FIRST (summary), then structural
    metadata, then code body — embeddings weight early tokens more heavily.
    """
    sym = chunk.symbol_path or chunk.file_path
    lines = f"{chunk.start_line}-{chunk.end_line}"
    parts: list[str] = []

    if summary:
        parts.append(summary)

    if chunk.chunk_type == "file":
        parts.append(f"File: {chunk.file_path}")
        parts.append(f"Module: {chunk.module_path}")
        if chunk.imports:
            parts.append(f"Imports: {', '.join(chunk.imports[:20])}")
    elif chunk.chunk_type == "class":
        parts.append(f"Class: {sym}")
        parts.append(f"File: {chunk.file_path}:{lines}")
    else:  # function | method
        kind = "Function" if chunk.chunk_type == "function" else "Method"
        parts.append(f"{kind}: {sym}")
        parts.append(f"File: {chunk.file_path}:{lines}")
        if chunk.decorators:
            parts.append("Decorators: @" + ", @".join(chunk.decorators[:5]))
        if chunk.calls:
            parts.append(f"Calls: {', '.join(chunk.calls[:10])}")

    if chunk.docstring:
        parts.append(chunk.docstring[:500])

    parts.append("")  # blank separator before code
    parts.append(chunk.code[:EMBED_TEXT_CODE_CAP])

    return "\n".join(parts)


# ── Content hashing (for change detection / cache key) ────────────────
def content_hash_for_chunk(chunk: Chunk) -> str:
    """Stable hash of (chunk_type, code). Stored on the Weaviate row so we
    can detect unchanged chunks on re-index in Step 7's delta path."""
    return hashlib.sha256(
        f"{chunk.chunk_type}::{chunk.code}".encode("utf-8")
    ).hexdigest()


# ── Parallel summarization ────────────────────────────────────────────
def _summarize_batch(summarizer: Summarizer, batch: list[Chunk]) -> tuple[list[str], int]:
    """Run summaries with a thread pool (I/O-bound; OpenAI API latency-bound).

    Returns (summaries, cache_hits).
    """
    summaries: list[str] = [""] * len(batch)
    hits = 0
    with ThreadPoolExecutor(max_workers=SUMMARY_CONCURRENCY) as ex:
        for i, (text, hit) in enumerate(ex.map(summarizer.summarize, batch)):
            summaries[i] = text
            if hit:
                hits += 1
    return summaries, hits


# ── Upsert ────────────────────────────────────────────────────────────
def _upsert_batch(
    client: weaviate.WeaviateClient,
    tenant: str,
    chunks: list[Chunk],
    summaries: list[str],
    vectors: list[list[float]],
) -> tuple[int, int]:
    """Upsert a batch. Returns (inserted, errors)."""
    coll = client.collections.use(COLLECTION_NAME).with_tenant(tenant)
    objects: list[DataObject] = []
    for c, s, v in zip(chunks, summaries, vectors):
        props = chunk_to_properties(c, tenant)
        # Indexer-populated fields (overwrite the empty defaults from the chunker)
        props["summary"] = s
        props["content_hash"] = content_hash_for_chunk(c)
        objects.append(DataObject(
            properties=props,
            uuid=chunk_uuid(tenant, c),
            vector=v,
        ))
    result = coll.data.insert_many(objects)
    inserted = len(result.uuids) if result.uuids else 0
    errors = len(result.errors) if result.errors else 0
    return inserted, errors


# ── Top-level orchestrator ────────────────────────────────────────────
def index_repo(
    repo_path: Path,
    *,
    tenant: str,
    drop: bool = False,
    limit: int | None = None,
    progress: bool = True,
) -> dict:
    """End-to-end indexing of a repo into the named tenant.

    Args:
        repo_path: absolute path to the repo root (e.g. /app/repos/flask).
        tenant: Weaviate tenant name (typically the repo name).
        drop: when True, delete the collection first (loses ALL tenants).
        limit: optional cap on chunks for dev runs.
        progress: tqdm progress bar.

    Returns: stats dict with discovered/inserted/by_type/cache rates/timing.
    """
    embedder = Embedder()
    summarizer = Summarizer()

    # ── Phase 1: discover all chunks (cheap — just tree-sitter parsing) ──
    print(f"== Discovering chunks in {repo_path} ==")
    t0 = time.time()
    all_chunks: list[Chunk] = list(extract_from_repo(repo_path))
    if limit is not None:
        all_chunks = all_chunks[:limit]
    discover_elapsed = time.time() - t0
    print(f"  Discovered {len(all_chunks)} chunks in {discover_elapsed:.1f}s")

    by_type: dict[str, int] = {}
    for c in all_chunks:
        by_type[c.chunk_type] = by_type.get(c.chunk_type, 0) + 1
    print(f"  Counts: {by_type}")

    if not all_chunks:
        return {"discovered": 0, "inserted": 0, "final_count": 0,
                "by_type": {}, "elapsed_seconds": 0.0, "tenant": tenant}

    # ── Phase 2: schema + tenant readiness ──────────────────────────────
    with weaviate_client() as client:
        if drop:
            if drop_schema(client):
                print(f"  Dropped existing collection {COLLECTION_NAME}")
        init_schema(client)
        ensure_tenant(client, tenant)
        print(f"  Tenant '{tenant}' ready")
        print(f"  Embedder: {embedder.provider}/{embedder.model} (dim={embedder.expected_dimension})")
        print(f"  Summarizer: {summarizer.provider}/{summarizer.model}")

        # ── Phase 3: batched summarize → embed → upsert ─────────────────
        t_pipeline_start = time.time()
        total_inserted = 0
        total_errors = 0
        total_embed_hits = 0
        total_summary_hits = 0

        with tqdm(total=len(all_chunks), desc="Indexing", disable=not progress) as pbar:
            for start in range(0, len(all_chunks), CHUNK_BATCH_SIZE):
                batch = all_chunks[start:start + CHUNK_BATCH_SIZE]

                # 3a. Summaries (parallel, cache-aware)
                summaries, sum_hits = _summarize_batch(summarizer, batch)
                total_summary_hits += sum_hits

                # 3b. Embed texts (single batched API call per group, cache-aware)
                embed_texts = [build_embed_text(c, s) for c, s in zip(batch, summaries)]
                vectors, e_stats = embedder.embed(embed_texts)
                total_embed_hits += e_stats["hits"]

                # 3c. Upsert (single batched call)
                ins, errs = _upsert_batch(client, tenant, batch, summaries, vectors)
                total_inserted += ins
                total_errors += errs

                pbar.update(len(batch))
                pbar.set_postfix(
                    sum_hit=f"{total_summary_hits}/{start + len(batch)}",
                    emb_hit=f"{total_embed_hits}/{start + len(batch)}",
                    errs=total_errors,
                )

        elapsed = time.time() - t_pipeline_start
        final_count = count_chunks(client, tenant)

    return {
        "discovered": len(all_chunks),
        "inserted": total_inserted,
        "errors": total_errors,
        "final_count": final_count,
        "by_type": by_type,
        "embed_hit_rate": total_embed_hits / len(all_chunks),
        "summary_hit_rate": total_summary_hits / len(all_chunks),
        "elapsed_seconds": round(elapsed, 1),
        "tenant": tenant,
    }
