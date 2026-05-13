"""Chunk dataclass — the unit produced by the chunker and stored in Weaviate."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Chunk:
    chunk_type: str                       # "file" | "class" | "function" | "method" | "doc"
    file_path: str                        # repo-relative POSIX path
    start_line: int                       # 1-indexed inclusive
    end_line: int                         # 1-indexed inclusive
    symbol_name: str                      # last segment of symbol_path
    symbol_path: str                      # e.g. "flask.app.Flask.dispatch_request"
    parent_symbol: str | None             # class name for methods, else None
    module_path: str                      # e.g. "flask.app"
    language: str
    code: str                             # raw source slice (no context prefix yet)
    docstring: str | None
    imports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    is_test: bool = False
    is_private: bool = False
    is_async: bool = False
    loc: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
