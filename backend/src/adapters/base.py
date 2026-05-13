"""LanguageAdapter Protocol — per-language parsing concerns.

Adding a new language = drop in a new adapter implementing this protocol.
The chunker (extract.py) and downstream stages stay untouched.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from tree_sitter import Node, Tree


@runtime_checkable
class LanguageAdapter(Protocol):
    language_name: str
    extensions: list[str]
    function_node_types: set[str]
    class_node_types: set[str]
    decorated_node_types: set[str]

    def parse(self, source: bytes) -> Tree: ...

    def get_symbol_name(self, node: Node) -> str | None: ...
    def get_docstring(self, node: Node) -> str | None: ...
    def get_decorators(self, node: Node) -> list[str]: ...
    def get_calls(self, body_node: Node) -> list[str]: ...
    def extract_module_imports(self, root: Node) -> list[str]: ...
    def is_async(self, node: Node) -> bool: ...
    def module_path_from_file(self, repo_relative_path: str) -> str: ...
