"""Dev CLI — exposes pipeline stages without going through HTTP."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import click

from src.chunks import Chunk
from src.extract import extract_from_repo


@click.group()
def cli() -> None:
    """Codebase Q&A Agent — dev CLI."""


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--limit", default=50, type=int, show_default=True,
              help="Max chunks to print (counts still report the full total).")
@click.option("--type", "chunk_type", default=None,
              type=click.Choice(["file", "class", "function", "method"]),
              help="Filter output by chunk_type.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON Lines.")
@click.option("--no-tests", is_flag=True, help="Exclude is_test=True chunks.")
def chunk(
    repo_path: Path,
    limit: int,
    chunk_type: str | None,
    as_json: bool,
    no_tests: bool,
) -> None:
    """Extract chunks from a repo and print them.

    Example:
        python -m src.cli chunk /app/repos/flask --limit 50
        python -m src.cli chunk /app/repos/flask --type class --json
    """
    printed = 0
    counts_by_type: dict[str, int] = {}
    test_counts: dict[str, int] = {}

    for c in extract_from_repo(repo_path):
        counts_by_type[c.chunk_type] = counts_by_type.get(c.chunk_type, 0) + 1
        if c.is_test:
            test_counts[c.chunk_type] = test_counts.get(c.chunk_type, 0) + 1
        if no_tests and c.is_test:
            continue
        if chunk_type and c.chunk_type != chunk_type:
            continue
        if printed >= limit:
            continue
        if as_json:
            click.echo(json.dumps(c.to_dict()))
        else:
            _pretty_print(c)
        printed += 1

    click.echo("", err=True)
    click.secho("== Counts ==", err=True, fg="green", bold=True)
    for k in sorted(counts_by_type):
        ts = test_counts.get(k, 0)
        click.echo(f"  {k:<10s}  total={counts_by_type[k]:<6d}  in tests={ts}", err=True)
    click.echo(f"  {'TOTAL':<10s}  total={sum(counts_by_type.values())}", err=True)


def _pretty_print(c: Chunk) -> None:
    header = (
        f"[{c.chunk_type}] {c.symbol_path or '<root>'}  "
        f"({c.file_path}:{c.start_line}-{c.end_line})  loc={c.loc}"
    )
    click.secho(header, fg="cyan", bold=True)
    flags: list[str] = []
    if c.is_test:
        flags.append("test")
    if c.is_async:
        flags.append("async")
    if c.is_private:
        flags.append("private")
    if flags:
        click.echo(f"  flags: {', '.join(flags)}")
    if c.decorators:
        click.echo(f"  decorators: {c.decorators}")
    if c.docstring:
        doc = c.docstring.replace("\n", " ")
        click.echo(f"  doc: {doc[:120]}{'...' if len(doc) > 120 else ''}")
    if c.imports:
        imps = c.imports[:5]
        suffix = f" (+{len(c.imports) - 5} more)" if len(c.imports) > 5 else ""
        click.echo(f"  imports: {imps}{suffix}")
    if c.calls:
        calls = c.calls[:5]
        suffix = f" (+{len(c.calls) - 5} more)" if len(c.calls) > 5 else ""
        click.echo(f"  calls:   {calls}{suffix}")
    # First 3 non-blank lines of code
    code_lines = [ln for ln in c.code.splitlines() if ln.strip()][:3]
    preview = " | ".join(ln.strip() for ln in code_lines)
    if preview:
        click.echo(f"  code:    {preview[:180]}{'...' if len(preview) > 180 else ''}")
    click.echo()


@cli.command("init-schema")
@click.option("--drop", is_flag=True, help="Delete and recreate the collection.")
def init_schema_cmd(drop: bool) -> None:
    """Create the multi-tenant CodeChunk_v1 collection in Weaviate."""
    from src.store import COLLECTION_NAME, init_schema, weaviate_client
    with weaviate_client() as client:
        created = init_schema(client, drop=drop)
        if created:
            click.secho(f"✓ Created collection {COLLECTION_NAME}", fg="green")
        else:
            click.secho(f"  Collection {COLLECTION_NAME} already exists "
                        f"(use --drop to recreate)", fg="yellow")


@cli.command("drop-schema")
@click.confirmation_option(prompt="Delete the CodeChunk_v1 collection?")
def drop_schema_cmd() -> None:
    """Delete the CodeChunk_v1 collection (irreversible)."""
    from src.store import COLLECTION_NAME, drop_schema, weaviate_client
    with weaviate_client() as client:
        if drop_schema(client):
            click.secho(f"✓ Deleted collection {COLLECTION_NAME}", fg="green")
        else:
            click.secho(f"  Collection {COLLECTION_NAME} did not exist", fg="yellow")


@cli.command("insert-test")
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--tenant", default="test", show_default=True, help="Tenant name to insert into.")
@click.option("--limit", default=10, show_default=True, type=int, help="Chunks to insert.")
def insert_test_cmd(repo_path: Path, tenant: str, limit: int) -> None:
    """Insert N chunks from a repo into a tenant (no vectors yet — Step 3 only)."""
    from src.store import ensure_tenant, insert_chunks, weaviate_client

    # Take a curated mix: 2 file + 3 class + 5 function chunks (ensures
    # tokenization tests cover all types).
    by_type: dict[str, list[Chunk]] = {"file": [], "class": [], "function": [], "method": []}
    for c in extract_from_repo(repo_path):
        by_type[c.chunk_type].append(c)
        if all(len(by_type[t]) >= 5 for t in ("file", "class", "function", "method")):
            break

    selected: list[Chunk] = (
        by_type["file"][:2] + by_type["class"][:3]
        + by_type["function"][:3] + by_type["method"][:2]
    )[:limit]

    if not selected:
        click.secho("✗ No chunks extracted — is the repo path correct?", fg="red")
        raise click.Abort()

    with weaviate_client() as client:
        created = ensure_tenant(client, tenant)
        if created:
            click.secho(f"  Created tenant '{tenant}'", fg="cyan")
        result = insert_chunks(client, selected, repo_name=tenant)
        click.secho(
            f"✓ Inserted {result['inserted']} chunks into tenant '{tenant}' "
            f"({result['errors']} errors)",
            fg="green" if result["errors"] == 0 else "yellow",
        )
        if result["first_errors"]:
            for e in result["first_errors"]:
                click.echo(f"  err [{e['idx']}]: {e['msg']}")


@cli.command()
@click.argument("query_text")
@click.option("--tenant", default="test", show_default=True)
@click.option("--limit", default=5, show_default=True, type=int)
def query(query_text: str, tenant: str, limit: int) -> None:
    """BM25 search against a tenant — used in Step 3 to validate the schema.

    Hybrid (vector + BM25) lands in Step 6 once embeddings exist.
    """
    from src.store import bm25_search, weaviate_client
    with weaviate_client() as client:
        hits = bm25_search(client, tenant, query_text, limit=limit)
        if not hits:
            click.secho(f"  No hits in tenant '{tenant}'", fg="yellow")
            return
        click.secho(f"== Top {len(hits)} hits for '{query_text}' ==", fg="green", bold=True)
        for i, h in enumerate(hits, 1):
            click.echo(
                f"  [{i}] score={h['score']:.3f}  [{h['chunk_type']}] "
                f"{h['symbol_path']}  ({h['file_path']}:{h['start_line']}-{h['end_line']})"
            )


@cli.command()
@click.argument("tenant")
def count(tenant: str) -> None:
    """Print the chunk count for a tenant."""
    from src.store import count_chunks, weaviate_client
    with weaviate_client() as client:
        n = count_chunks(client, tenant)
        click.echo(f"tenant '{tenant}': {n} chunks")


@cli.command("list-tenants")
def list_tenants_cmd() -> None:
    """List all tenants in the collection."""
    from src.store import list_tenants, weaviate_client
    with weaviate_client() as client:
        tenants = list_tenants(client)
        if not tenants:
            click.echo("(no tenants)")
            return
        for t in tenants:
            click.echo(f"  {t}")


@cli.command("embed-sample")
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--limit", default=20, show_default=True, type=int)
def embed_sample_cmd(repo_path: Path, limit: int) -> None:
    """Embed + summarize N sample chunks. Validates Step 4 factories + cache.

    Run twice to verify the second pass is ~100% cache hits.
    """
    import time
    from src.cache import cache_stats
    from src.embed import Embedder
    from src.summarize import Summarizer

    # Balanced sample across chunk types
    by_type: dict[str, list[Chunk]] = {"file": [], "class": [], "function": [], "method": []}
    target_per_type = max(1, limit // 4)
    for c in extract_from_repo(repo_path):
        if c.chunk_type in by_type and len(by_type[c.chunk_type]) < target_per_type * 2:
            by_type[c.chunk_type].append(c)
        if sum(len(v) for v in by_type.values()) >= limit * 2:
            break
    selected: list[Chunk] = []
    for t in ("file", "class", "function", "method"):
        selected.extend(by_type[t][:target_per_type])
    selected = selected[:limit]
    if not selected:
        click.secho("No chunks extracted — is the repo path correct?", fg="red")
        raise click.Abort()

    click.secho(f"== Selected {len(selected)} chunks ==", fg="green", bold=True)
    by_type_count: dict[str, int] = {}
    for c in selected:
        by_type_count[c.chunk_type] = by_type_count.get(c.chunk_type, 0) + 1
    for t, n in sorted(by_type_count.items()):
        click.echo(f"  {t:<10s}: {n}")

    # ── Embedding ──────────────────────────────────────────────
    embedder = Embedder()
    click.secho(
        f"\n== Embedding: provider={embedder.provider} model={embedder.model} ==",
        fg="green", bold=True,
    )
    # The embedding input mirrors what the indexing pipeline will use
    # (Strategy C: symbol_path + docstring + code preview). Full Strategy
    # C concatenation lands when the indexer wires in Step 5.
    texts = [
        f"{c.symbol_path}\n{c.docstring or ''}\n{c.code[:1500]}"
        for c in selected
    ]
    t0 = time.time()
    vectors, e_stats = embedder.embed(texts)
    elapsed = time.time() - t0
    click.echo(
        f"  total={e_stats['total']} hits={e_stats['hits']} "
        f"misses={e_stats['misses']} hit_rate={e_stats['hit_rate']*100:.0f}% "
        f"dim={e_stats['dimension']} took={elapsed:.1f}s"
    )

    # ── Summarization ──────────────────────────────────────────
    summarizer = Summarizer()
    click.secho(
        f"\n== Summary: provider={summarizer.provider} model={summarizer.model} ==",
        fg="green", bold=True,
    )
    t0 = time.time()
    summaries: list[tuple[Chunk, str, bool]] = []
    hits = 0
    for c in selected:
        s, hit = summarizer.summarize(c)
        summaries.append((c, s, hit))
        if hit:
            hits += 1
    elapsed = time.time() - t0
    click.echo(
        f"  total={len(selected)} hits={hits} misses={len(selected)-hits} "
        f"hit_rate={hits/len(selected)*100:.0f}% took={elapsed:.1f}s"
    )

    # ── Sample summaries (eyeball distinctness) ───────────────
    click.secho("\n== Sample summaries (5) ==", fg="green", bold=True)
    for c, s, _ in summaries[:5]:
        click.secho(f"[{c.chunk_type}] {c.symbol_path}", fg="cyan", bold=True)
        click.echo(f"  {s}\n")

    # ── Cache totals ──────────────────────────────────────────
    stats = cache_stats()
    click.secho("== Cache totals ==", fg="green", bold=True)
    click.echo(f"  embeddings: {stats['embeddings']['total']} "
               f"(by provider/model: {stats['embeddings']['by_provider_model']})")
    click.echo(f"  summaries:  {stats['summaries']['total']} "
               f"(by provider/model: {stats['summaries']['by_provider_model']})")


if __name__ == "__main__":
    cli()
