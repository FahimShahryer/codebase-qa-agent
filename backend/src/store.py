"""Weaviate client wrapper — connection, schema, tenancy, batch I/O.

verified: /weaviate/weaviate-python-client v4 (May 2026)
- weaviate.connect_to_local(host=, port=, grpc_port=) — REST + gRPC
- client.collections.create(...) with multi_tenancy_config + vectorizer=none
- client.collections.use("name") returns Collection
- collection.with_tenant("x").data.insert_many([DataObject(...)])
- collection.tenants.create([Tenant(name=...)])
- Tokenization.{FIELD, LOWERCASE, WORD, WHITESPACE}
- Filter.by_property / Filter.by_id
- Aggregate.over_all(total_count=True)
"""
from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from typing import Iterator

import weaviate
from weaviate.classes.config import (
    Configure,
    DataType,
    Property,
    Tokenization,
    VectorDistances,
)
from weaviate.classes.data import DataObject
from weaviate.classes.query import Filter, MetadataQuery
from weaviate.classes.tenants import Tenant

from src.chunks import Chunk
from src.config import settings

# ── Constants ────────────────────────────────────────────────────────
COLLECTION_NAME = "CodeChunk_v1"
NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000000001")
EMBEDDING_DIM = 1536  # text-embedding-3-small dimension


# ── Connection ───────────────────────────────────────────────────────
def _url_host(url: str) -> str:
    return url.split("://")[-1].split(":")[0].split("/")[0]


def _url_port(url: str, default: int = 8080) -> int:
    tail = url.split("://")[-1]
    if ":" in tail:
        try:
            return int(tail.split(":")[1].split("/")[0])
        except (IndexError, ValueError):
            return default
    return default


@contextmanager
def weaviate_client() -> Iterator[weaviate.WeaviateClient]:
    """Context-managed Weaviate v4 client (REST + gRPC). Closes on exit."""
    client = weaviate.connect_to_local(
        host=_url_host(settings.WEAVIATE_URL),
        port=_url_port(settings.WEAVIATE_URL),
        grpc_port=settings.WEAVIATE_GRPC_PORT,
    )
    try:
        yield client
    finally:
        client.close()


# ── Schema ───────────────────────────────────────────────────────────
def schema_properties() -> list[Property]:
    """The full property schema. Tokenization choices per approach1.md Step 2.

    24 properties total. FIELD = exact-match-only (enums/ids), LOWERCASE =
    identifier-friendly (preserves underscores), WORD = natural-text splitting.
    """
    return [
        # ── Identity ────────────────────────────────────────────
        Property(name="chunk_id",      data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="content_hash",  data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        # ── Location / citation ─────────────────────────────────
        Property(name="repo_name",     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="file_path",     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        Property(name="start_line",    data_type=DataType.INT),
        Property(name="end_line",      data_type=DataType.INT),
        # ── Type / structure ────────────────────────────────────
        Property(name="chunk_type",    data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="language",      data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        Property(name="symbol_name",   data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE),
        Property(name="symbol_tokens", data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        Property(name="symbol_path",   data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        Property(name="parent_symbol", data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE),
        Property(name="module_path",   data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        # ── Searchable content ──────────────────────────────────
        Property(name="code",          data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        Property(name="code_raw",      data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                 index_searchable=False),
        Property(name="docstring",     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        Property(name="summary",       data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        # ── Cross-references ────────────────────────────────────
        Property(name="imports",       data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
        Property(name="calls",         data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.LOWERCASE),
        Property(name="decorators",    data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.LOWERCASE),
        # ── Flags ───────────────────────────────────────────────
        Property(name="is_test",       data_type=DataType.BOOL),
        Property(name="is_private",    data_type=DataType.BOOL),
        Property(name="is_async",      data_type=DataType.BOOL),
        # ── Metrics ─────────────────────────────────────────────
        Property(name="loc",           data_type=DataType.INT),
    ]


def init_schema(client: weaviate.WeaviateClient, *, drop: bool = False) -> bool:
    """Create the multi-tenant CodeChunk_v1 collection. Idempotent.

    Returns True if the collection was (re)created, False if it already existed.
    """
    if client.collections.exists(COLLECTION_NAME):
        if drop:
            client.collections.delete(COLLECTION_NAME)
        else:
            return False

    # verified: weaviate-client 4.21 — `vector_config=Configure.Vectors.self_provided`
    # is the current API (replaces deprecated vectorizer_config + vector_index_config).
    client.collections.create(
        name=COLLECTION_NAME,
        properties=schema_properties(),
        multi_tenancy_config=Configure.multi_tenancy(
            enabled=True,
            auto_tenant_creation=True,
        ),
        vector_config=Configure.Vectors.self_provided(   # BYO vectors
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE,
            ),
        ),
        inverted_index_config=Configure.inverted_index(
            bm25_b=0.75,
            bm25_k1=1.2,
        ),
    )
    return True


def drop_schema(client: weaviate.WeaviateClient) -> bool:
    """Delete the collection if it exists. Returns True if deleted."""
    if client.collections.exists(COLLECTION_NAME):
        client.collections.delete(COLLECTION_NAME)
        return True
    return False


# ── Tenants ──────────────────────────────────────────────────────────
def ensure_tenant(client: weaviate.WeaviateClient, tenant: str) -> bool:
    """Ensure a tenant exists. Returns True if newly created."""
    coll = client.collections.use(COLLECTION_NAME)
    if coll.tenants.exists(tenant):
        return False
    coll.tenants.create([Tenant(name=tenant)])
    return True


def list_tenants(client: weaviate.WeaviateClient) -> list[str]:
    coll = client.collections.use(COLLECTION_NAME)
    return list(coll.tenants.get().keys())


# ── Chunk → properties mapping ───────────────────────────────────────
def chunk_uuid(repo: str, chunk: Chunk) -> str:
    """Deterministic UUID5 by (repo, file_path, symbol_path). Stable across
    re-indexing — same symbol → same UUID even if code body changes
    (content_hash is a separate property for change detection)."""
    sp = chunk.symbol_path or chunk.file_path
    return str(uuid.uuid5(NAMESPACE, f"{repo}::{chunk.file_path}::{sp}"))


def _tokenize_identifier(name: str) -> str:
    """parse_args → 'parse_args parse args'
       parseArgs  → 'parseArgs parse Args'
       ParseArgs  → 'ParseArgs Parse Args'"""
    if not name:
        return ""
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z])|[A-Z]+|\d+", name)
    return f"{name} {' '.join(parts)}".strip()


def chunk_to_properties(chunk: Chunk, repo_name: str) -> dict:
    """Map a Chunk dataclass to the Weaviate property dict."""
    sp = chunk.symbol_path or chunk.file_path
    return {
        "chunk_id": f"{repo_name}::{chunk.file_path}::{sp}",
        "content_hash": "",                           # set by indexer in step 4+
        "repo_name": repo_name,
        "file_path": chunk.file_path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "chunk_type": chunk.chunk_type,
        "language": chunk.language,
        "symbol_name": chunk.symbol_name,
        "symbol_tokens": _tokenize_identifier(chunk.symbol_name),
        "symbol_path": chunk.symbol_path,
        "parent_symbol": chunk.parent_symbol or "",
        "module_path": chunk.module_path,
        "code": chunk.code,
        "code_raw": chunk.code,
        "docstring": chunk.docstring or "",
        "summary": "",                                # filled by indexer in step 4+
        "imports": chunk.imports,
        "calls": chunk.calls,
        "decorators": chunk.decorators,
        "is_test": chunk.is_test,
        "is_private": chunk.is_private,
        "is_async": chunk.is_async,
        "loc": chunk.loc,
    }


# ── Insertion ────────────────────────────────────────────────────────
def insert_chunks(
    client: weaviate.WeaviateClient,
    chunks: list[Chunk],
    *,
    repo_name: str,
    vectors: list[list[float]] | None = None,
) -> dict:
    """Insert/upsert chunks into a tenant (named by repo_name).

    Vectors are optional in step 3 (we only test BM25 here). When vectors are
    omitted, objects are inserted without vector indices — they remain
    queryable via BM25 / hybrid-with-alpha=0. Step 4 replaces with real ones.
    """
    coll = client.collections.use(COLLECTION_NAME).with_tenant(repo_name)

    objects: list[DataObject] = []
    for i, c in enumerate(chunks):
        cid = chunk_uuid(repo_name, c)
        vec = vectors[i] if vectors is not None else None
        objects.append(DataObject(
            properties=chunk_to_properties(c, repo_name),
            uuid=cid,
            vector=vec,
        ))

    result = coll.data.insert_many(objects)
    error_items = list(result.errors.items()) if result.errors else []
    return {
        "inserted": len(result.uuids) if result.uuids else 0,
        "errors": len(error_items),
        "first_errors": [{"idx": i, "msg": e.message} for i, e in error_items[:3]],
    }


# ── Counting & querying ──────────────────────────────────────────────
def count_chunks(client: weaviate.WeaviateClient, tenant: str) -> int:
    coll = client.collections.use(COLLECTION_NAME).with_tenant(tenant)
    return coll.aggregate.over_all(total_count=True).total_count or 0


def bm25_search(
    client: weaviate.WeaviateClient,
    tenant: str,
    query: str,
    *,
    limit: int = 5,
) -> list[dict]:
    """BM25-only search with property weighting. Used in Step 3 to validate
    the schema and tokenization before the embedding pipeline lands (Step 4+).
    Full hybrid retrieval pipeline arrives in Step 6.
    """
    coll = client.collections.use(COLLECTION_NAME).with_tenant(tenant)
    response = coll.query.bm25(
        query=query,
        query_properties=[
            "symbol_name^4",
            "symbol_tokens^3",
            "symbol_path^2.5",
            "summary^2",
            "docstring^2",
            "file_path^1.5",
            "code^1",
        ],
        limit=limit,
        return_metadata=MetadataQuery(score=True, explain_score=True),
    )
    return [
        {
            "symbol_path": o.properties.get("symbol_path"),
            "file_path": o.properties.get("file_path"),
            "chunk_type": o.properties.get("chunk_type"),
            "start_line": o.properties.get("start_line"),
            "end_line": o.properties.get("end_line"),
            "score": o.metadata.score if o.metadata else None,
        }
        for o in response.objects
    ]
