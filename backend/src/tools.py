"""7 agent tools — exposed to the LLM via @tool decorator.

Tool selection guide (also embedded in the agent's system prompt):
  - search_code:        default for any conceptual / content question
  - read_file:          read raw file content after search points to a target
  - list_directory:     explore repo structure
  - summarize_module:   O(1) lookup of precomputed file/class summary
  - find_callers:       reverse call graph — "what calls X?"
  - find_importers:     reverse import graph — "who depends on X module?"
  - find_definition:    exact identifier lookup
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool
from weaviate.classes.query import Filter

from src.config import settings
from src.detect import (
    BINARY_EXTENSIONS,
    SKIP_DIRS,
    is_secret_filename,
    should_skip_dir,
)
from src.retrieve import RetrievedChunk, search_code as _retrieve
from src.store import COLLECTION_NAME, weaviate_client

REPOS_ROOT = Path("/app/repos")


# ── Formatting helpers ───────────────────────────────────────────────
def _format_chunk(idx: int, c: RetrievedChunk, *, code_lines: int = 12) -> str:
    """Format a single chunk for the agent's tool result."""
    lines: list[str] = []
    lines.append(
        f"[{idx}] {c.file_path}:{c.start_line}-{c.end_line} "
        f"({c.chunk_type}: {c.symbol_path or '<root>'})"
    )
    if c.summary:
        lines.append(f"    Summary: {c.summary[:280]}")
    if c.decorators:
        lines.append(f"    Decorators: @{', @'.join(c.decorators[:5])}")
    if c.calls:
        lines.append(f"    Calls: {', '.join(c.calls[:8])}")
    if c.docstring and not c.summary:
        ds = c.docstring.replace("\n", " ")[:200]
        lines.append(f"    Docstring: {ds}")
    if c.code:
        lines.append("    Code:")
        for line in c.code.splitlines()[:code_lines]:
            lines.append(f"      {line}")
        if len(c.code.splitlines()) > code_lines:
            lines.append("      ...")
    return "\n".join(lines)


def _format_chunks(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No matching chunks found."
    return "\n\n".join(_format_chunk(i, c) for i, c in enumerate(chunks, 1))


def _row_to_chunk(obj):
    """Convert Weaviate object to RetrievedChunk (shared with retrieve.py)."""
    from src.retrieve import _row_to_chunk as _converter
    return _converter(obj, source="search")


# ── Tool 1: search_code (default) ────────────────────────────────────
@tool
def search_code(query: str, max_results: int = 5) -> str:
    """Semantic + keyword hybrid search over the indexed codebase.

    This is the DEFAULT tool — use it for any conceptual or content-based
    question about the codebase (how it works, where something happens,
    what does X do, etc.). Returns top-k chunks with file paths, line
    ranges, summaries, and code excerpts.

    Args:
        query: natural-language question or keywords.
        max_results: top-k chunks to return (1-10, default 5).
    """
    max_results = max(1, min(int(max_results), 10))
    chunks = _retrieve(
        query, tenant=settings.REPO_NAME, top_k=max_results, expand=True,
    )
    return _format_chunks(chunks)


# ── Tool 2: read_file ────────────────────────────────────────────────
@tool
def read_file(path: str, start: int = 1, end: int = 0) -> str:
    """Read a file slice from the indexed repo.

    Use AFTER search_code when you need more context than the search
    returned (e.g. the surrounding function, the whole class body).

    Args:
        path: file path relative to the repo root (e.g. "src/flask/app.py").
        start: 1-indexed first line to include (default: 1).
        end: 1-indexed last line, inclusive. 0 means "to EOF" (default: 0).
    """
    # Enforce skip-list — never read secrets / binaries / out-of-repo paths
    fname = Path(path).name
    if fname.startswith(".") or is_secret_filename(fname):
        return f"Refused: '{path}' looks like a secret or hidden file."
    if Path(path).suffix.lower() in BINARY_EXTENSIONS:
        return f"Refused: '{path}' is a binary file."

    repo_root = (REPOS_ROOT / settings.REPO_NAME).resolve()
    target = (repo_root / path).resolve()
    try:
        target.relative_to(repo_root)
    except ValueError:
        return f"Refused: '{path}' is outside the indexed repo."

    if not target.is_file():
        return f"File not found: {path}"

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Read error: {e}"

    all_lines = text.splitlines()
    s = max(1, int(start))
    e = int(end) if end and end > 0 else len(all_lines)
    e = min(e, len(all_lines))
    if s > e:
        return f"Invalid range: start={s} > end={e}"

    excerpt = all_lines[s - 1:e]
    # Number each line for the LLM's reference
    body = "\n".join(f"{s + i:>5d}  {line}" for i, line in enumerate(excerpt))
    return f"{path}:{s}-{e}\n{body}"


# ── Tool 3: list_directory ───────────────────────────────────────────
@tool
def list_directory(path: str = "") -> str:
    """List files and subdirectories under a repo-relative path.

    Use for structural exploration: "what's in the auth module?",
    "list the test files", etc. Returns immediate children only.

    Args:
        path: directory relative to the repo root. Empty string = repo root.
    """
    repo_root = (REPOS_ROOT / settings.REPO_NAME).resolve()
    target = (repo_root / path).resolve() if path else repo_root
    try:
        target.relative_to(repo_root)
    except ValueError:
        return f"Refused: '{path}' is outside the indexed repo."
    if not target.is_dir():
        return f"Not a directory: {path or '<repo root>'}"

    dirs: list[str] = []
    files: list[str] = []
    for entry in sorted(target.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if should_skip_dir(entry.name):
                continue
            dirs.append(f"  📁 {entry.name}/")
        else:
            if is_secret_filename(entry.name):
                continue
            files.append(f"  📄 {entry.name}")

    out = [f"Contents of {path or '<repo root>'}:"]
    out.extend(dirs)
    out.extend(files)
    if not dirs and not files:
        out.append("  (empty)")
    return "\n".join(out)


# ── Tool 4: summarize_module ─────────────────────────────────────────
@tool
def summarize_module(symbol_path: str) -> str:
    """Look up the precomputed LLM summary for a file or class.

    Fastest tool — single Weaviate filter query against a precomputed
    summary field. Use for "what does X do?" at a file or class level.

    Args:
        symbol_path: dotted path like "flask.app" (file) or
                     "flask.app.Flask" (class). Exact match.
    """
    with weaviate_client() as client:
        coll = client.collections.use(COLLECTION_NAME).with_tenant(settings.REPO_NAME)
        r = coll.query.fetch_objects(
            filters=(
                Filter.by_property("symbol_path").equal(symbol_path)
                & (
                    Filter.by_property("chunk_type").equal("file")
                    | Filter.by_property("chunk_type").equal("class")
                )
            ),
            limit=1,
        )
    if not r.objects:
        return f"No file or class found at symbol_path='{symbol_path}'."
    p = r.objects[0].properties
    return (
        f"{p.get('chunk_type')}: {p.get('symbol_path')}\n"
        f"  file: {p.get('file_path')}:{p.get('start_line')}-{p.get('end_line')}\n"
        f"  summary: {p.get('summary', '')}"
    )


# ── Tool 5: find_callers ─────────────────────────────────────────────
@tool
def find_callers(symbol_name: str, max_results: int = 10) -> str:
    """Find functions/methods that CALL the given symbol_name (reverse call graph).

    Use for "what calls X?" / "where is X used?" — semantic search misses
    this because callers don't necessarily contain the callee's docs.

    Args:
        symbol_name: bare function/method name (no parens, no dots).
                     Example: "make_response".
        max_results: max chunks to return (1-30, default 10).
    """
    max_results = max(1, min(int(max_results), 30))
    with weaviate_client() as client:
        coll = client.collections.use(COLLECTION_NAME).with_tenant(settings.REPO_NAME)
        r = coll.query.fetch_objects(
            filters=Filter.by_property("calls").contains_any([symbol_name]),
            limit=max_results,
        )
    chunks = [_row_to_chunk(o) for o in r.objects]
    if not chunks:
        return f"No callers of '{symbol_name}' found."
    return f"Found {len(chunks)} caller(s) of '{symbol_name}':\n\n" + _format_chunks(chunks)


# ── Tool 6: find_importers ───────────────────────────────────────────
@tool
def find_importers(module_name: str, max_results: int = 10) -> str:
    """Find files that import the given module (reverse import graph).

    Use for "who depends on X?" / "what uses this module?".

    Args:
        module_name: importable name like "werkzeug" or "flask.sessions".
        max_results: max files to return (1-30, default 10).
    """
    max_results = max(1, min(int(max_results), 30))
    with weaviate_client() as client:
        coll = client.collections.use(COLLECTION_NAME).with_tenant(settings.REPO_NAME)
        r = coll.query.fetch_objects(
            filters=(
                Filter.by_property("imports").contains_any([module_name])
                & Filter.by_property("chunk_type").equal("file")
            ),
            limit=max_results,
        )
    chunks = [_row_to_chunk(o) for o in r.objects]
    if not chunks:
        return f"No files import '{module_name}'."
    return (
        f"Found {len(chunks)} file(s) importing '{module_name}':\n\n"
        + _format_chunks(chunks)
    )


# ── Tool 7: find_definition ──────────────────────────────────────────
@tool
def find_definition(symbol_name: str) -> str:
    """Find the exact source location(s) of a symbol by name.

    Use when the user gives an exact identifier and wants its source
    (NOT to be confused with usage sites — for that use find_callers).

    Args:
        symbol_name: bare name (no parens). Example: "Blueprint", "render_template".
    """
    with weaviate_client() as client:
        coll = client.collections.use(COLLECTION_NAME).with_tenant(settings.REPO_NAME)
        r = coll.query.fetch_objects(
            filters=Filter.by_property("symbol_name").equal(symbol_name),
            limit=10,
        )
    chunks = [_row_to_chunk(o) for o in r.objects]
    if not chunks:
        return f"No definition found for '{symbol_name}'."
    # Sort: classes > methods/functions > files
    rank = {"class": 0, "function": 1, "method": 1, "file": 2}
    chunks.sort(key=lambda c: rank.get(c.chunk_type, 3))
    return f"Found {len(chunks)} definition(s) of '{symbol_name}':\n\n" + _format_chunks(chunks)


# ── Tool registry (consumed by agent.py) ─────────────────────────────
ALL_TOOLS = [
    search_code,
    read_file,
    list_directory,
    summarize_module,
    find_callers,
    find_importers,
    find_definition,
]
