"""Extract Chunks from files using language adapters.

Step 2 produces three chunk types per Python file:
- one `file` chunk per source file (module-level summary + imports)
- one `class` chunk per top-level class (also recurses for methods)
- one `function` chunk per top-level function, one `method` chunk per class method

Decorated definitions are kept whole (`@app.route` + body in a single chunk).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from tree_sitter import Node

from src.adapters.python import PythonAdapter, _string_text
from src.chunks import Chunk
from src.detect import DiscoveredFile, walk_repo

_python_adapter = PythonAdapter()


def extract_from_repo(repo_root: Path) -> Iterator[Chunk]:
    """Yield all chunks from a repo by walking files and running adapters."""
    repo_root = repo_root.resolve()
    for f in walk_repo(repo_root):
        if f.language == "python":
            yield from _extract_python_file(f)
        # Markdown/doc adapters wire in later steps.


def _extract_python_file(f: DiscoveredFile) -> Iterator[Chunk]:
    adapter = _python_adapter
    try:
        source = f.path.read_bytes()
    except OSError:
        return
    if not source.strip():
        return

    try:
        tree = adapter.parse(source)
    except Exception:
        return  # best-effort: skip unparseable files

    root = tree.root_node
    module_path = adapter.module_path_from_file(f.repo_relative)
    imports = adapter.extract_module_imports(root)

    # ── Pass 1: walk top-level, emit class/function/method chunks ─────
    symbol_chunks: list[Chunk] = []
    top_level_symbols: list[str] = []
    for top in root.children:
        if top.type in {"comment", "expression_statement"} and top != root.children[0]:
            continue
        chunks = _extract_top_level(top, adapter, f, module_path, imports, source)
        for c in chunks:
            if c.chunk_type in ("class", "function"):
                top_level_symbols.append(c.symbol_name)
            symbol_chunks.append(c)

    # ── Pass 2: emit the file-level chunk first (used as module summary) ──
    file_text = source.decode("utf-8", errors="replace")
    file_chunk = Chunk(
        chunk_type="file",
        file_path=f.repo_relative,
        start_line=1,
        end_line=max(1, file_text.count("\n") + (0 if file_text.endswith("\n") else 1)),
        symbol_name=module_path.split(".")[-1] if module_path else f.path.stem,
        symbol_path=module_path,
        parent_symbol=None,
        module_path=module_path,
        language="python",
        code=file_text,
        docstring=_module_docstring(root),
        imports=imports,
        calls=[],
        decorators=[],
        is_test=f.is_test,
        is_private=False,
        is_async=False,
        loc=file_text.count("\n") + 1,
    )
    yield file_chunk

    yield from symbol_chunks


def _module_docstring(root: Node) -> str | None:
    """Module-level docstring = first expression_statement-string-literal."""
    for stmt in root.named_children:
        if stmt.type == "expression_statement":
            if stmt.named_child_count == 1 and stmt.named_children[0].type == "string":
                return _string_text(stmt.named_children[0])
            return None
        return None
    return None


def _extract_top_level(
    node: Node,
    adapter: PythonAdapter,
    f: DiscoveredFile,
    module_path: str,
    imports: list[str],
    source: bytes,
) -> list[Chunk]:
    """Extract chunks rooted at a single top-level node."""
    chunks: list[Chunk] = []
    inner: Node = node
    decorators: list[str] = []

    if node.type == "decorated_definition":
        decorators = adapter.get_decorators(node)
        found_inner = False
        for child in node.named_children:
            if child.type in adapter.function_node_types | adapter.class_node_types:
                inner = child
                found_inner = True
                break
        if not found_inner:
            return chunks

    if inner.type in adapter.class_node_types:
        chunks.append(_class_chunk(inner, node, adapter, f, module_path, imports, decorators, source))
        # Recurse into class body for methods
        class_name = adapter.get_symbol_name(inner)
        body = inner.child_by_field_name("body")
        if body is not None and class_name is not None:
            for child in body.named_children:
                method_decorators: list[str] = []
                method_outer: Node = child
                method_inner: Node = child
                if child.type == "decorated_definition":
                    method_decorators = adapter.get_decorators(child)
                    found_meth = False
                    for sub in child.named_children:
                        if sub.type in adapter.function_node_types:
                            method_inner = sub
                            found_meth = True
                            break
                    if not found_meth:
                        continue
                if method_inner.type in adapter.function_node_types:
                    chunks.append(
                        _function_chunk(
                            method_inner, method_outer, adapter, f, module_path, imports,
                            method_decorators, source,
                            parent_symbol=class_name,
                            chunk_type="method",
                        )
                    )
    elif inner.type in adapter.function_node_types:
        chunks.append(
            _function_chunk(
                inner, node, adapter, f, module_path, imports, decorators, source,
                parent_symbol=None,
                chunk_type="function",
            )
        )

    return chunks


def _class_chunk(
    inner: Node, outer: Node, adapter: PythonAdapter,
    f: DiscoveredFile, module_path: str, imports: list[str],
    decorators: list[str], source: bytes,
) -> Chunk:
    name = adapter.get_symbol_name(inner) or "<unnamed>"
    start_line, end_line = _line_range(outer)
    code = _slice_source(source, outer)
    return Chunk(
        chunk_type="class",
        file_path=f.repo_relative,
        start_line=start_line,
        end_line=end_line,
        symbol_name=name,
        symbol_path=f"{module_path}.{name}" if module_path else name,
        parent_symbol=None,
        module_path=module_path,
        language="python",
        code=code,
        docstring=adapter.get_docstring(inner),
        imports=imports,
        calls=[],
        decorators=decorators,
        is_test=f.is_test,
        is_private=name.startswith("_") and not (name.startswith("__") and name.endswith("__")),
        is_async=False,
        loc=end_line - start_line + 1,
    )


def _function_chunk(
    inner: Node, outer: Node, adapter: PythonAdapter,
    f: DiscoveredFile, module_path: str, imports: list[str],
    decorators: list[str], source: bytes,
    parent_symbol: str | None, chunk_type: str,
) -> Chunk:
    name = adapter.get_symbol_name(inner) or "<unnamed>"
    start_line, end_line = _line_range(outer)
    code = _slice_source(source, outer)
    body = inner.child_by_field_name("body")
    calls = adapter.get_calls(body) if body is not None else []

    if parent_symbol:
        symbol_path = (
            f"{module_path}.{parent_symbol}.{name}" if module_path
            else f"{parent_symbol}.{name}"
        )
    else:
        symbol_path = f"{module_path}.{name}" if module_path else name

    return Chunk(
        chunk_type=chunk_type,
        file_path=f.repo_relative,
        start_line=start_line,
        end_line=end_line,
        symbol_name=name,
        symbol_path=symbol_path,
        parent_symbol=parent_symbol,
        module_path=module_path,
        language="python",
        code=code,
        docstring=adapter.get_docstring(inner),
        imports=imports,
        calls=calls,
        decorators=decorators,
        is_test=f.is_test,
        is_private=name.startswith("_") and not (name.startswith("__") and name.endswith("__")),
        is_async=adapter.is_async(inner),
        loc=end_line - start_line + 1,
    )


def _line_range(node: Node) -> tuple[int, int]:
    return node.start_point[0] + 1, node.end_point[0] + 1  # 1-indexed inclusive


def _slice_source(source: bytes, node: Node) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
