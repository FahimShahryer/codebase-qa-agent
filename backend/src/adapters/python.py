"""Python language adapter — uses tree-sitter-python.

verified: /tree-sitter/tree-sitter-python v0.25.0 + /tree-sitter/tree-sitter (May 2026)
- Language(tree_sitter_python.language()) capsule API
- Node types: function_definition, class_definition, decorated_definition,
  import_statement, import_from_statement, decorator, call, attribute,
  expression_statement, string, dotted_name, aliased_import, identifier
- Field names: "name", "body", "function", "attribute", "module_name"
"""
from __future__ import annotations

from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser, Tree

PY_LANGUAGE = Language(tree_sitter_python.language())
_parser = Parser(PY_LANGUAGE)


class PythonAdapter:
    language_name: str = "python"
    extensions: list[str] = [".py"]
    function_node_types: set[str] = {"function_definition"}
    class_node_types: set[str] = {"class_definition"}
    decorated_node_types: set[str] = {"decorated_definition"}

    def parse(self, source: bytes) -> Tree:
        return _parser.parse(source)

    def get_symbol_name(self, node: Node) -> str | None:
        """Return the name of a function/class def. Unwraps decorated_definition."""
        if node.type == "decorated_definition":
            for child in node.named_children:
                if child.type in self.function_node_types | self.class_node_types:
                    return self.get_symbol_name(child)
            return None
        name_node = node.child_by_field_name("name")
        if name_node is None or name_node.text is None:
            return None
        return name_node.text.decode("utf-8", errors="replace")

    def get_docstring(self, node: Node) -> str | None:
        """First string literal in the body of a fn/class."""
        if node.type == "decorated_definition":
            for child in node.named_children:
                if child.type in self.function_node_types | self.class_node_types:
                    return self.get_docstring(child)
            return None

        body = node.child_by_field_name("body")
        if body is None:
            return None
        for stmt in body.named_children:
            if stmt.type == "expression_statement":
                if (
                    stmt.named_child_count == 1
                    and stmt.named_children[0].type == "string"
                ):
                    return _string_text(stmt.named_children[0])
            break  # only the first statement counts
        return None

    def get_decorators(self, node: Node) -> list[str]:
        """Extract decorator names from a decorated_definition."""
        if node.type != "decorated_definition":
            return []
        decorators: list[str] = []
        for child in node.named_children:
            if child.type == "decorator":
                # decorator wraps a single expression (call/attribute/identifier)
                inner = child.named_children[0] if child.named_child_count else None
                if inner is None:
                    continue
                name = _extract_call_name(inner)
                if name:
                    decorators.append(name)
        return decorators

    def get_calls(self, body_node: Node) -> list[str]:
        """Walk the body collecting unique called function/method names."""
        calls: set[str] = set()

        def visit(n: Node) -> None:
            if n.type == "call":
                func = n.child_by_field_name("function")
                if func is not None:
                    name = _extract_call_name(func)
                    if name:
                        calls.add(name)
            for child in n.children:
                visit(child)

        visit(body_node)
        return sorted(calls)

    def extract_module_imports(self, root: Node) -> list[str]:
        """Top-level imports — module names only, deduped, in order."""
        seen: set[str] = set()
        result: list[str] = []
        for child in root.children:
            mods: list[str] = []
            if child.type == "import_statement":
                for sub in child.named_children:
                    if sub.type == "dotted_name":
                        mods.append(_dotted_name_text(sub))
                    elif sub.type == "aliased_import":
                        name_node = sub.child_by_field_name("name")
                        if name_node and name_node.type == "dotted_name":
                            mods.append(_dotted_name_text(name_node))
            elif child.type == "import_from_statement":
                module_node = child.child_by_field_name("module_name")
                if module_node and module_node.type in ("dotted_name", "relative_import"):
                    mods.append(_dotted_name_text(module_node))
            for m in mods:
                if m and m not in seen:
                    seen.add(m)
                    result.append(m)
        return result

    def is_async(self, node: Node) -> bool:
        if node.type == "decorated_definition":
            for child in node.named_children:
                if child.type in self.function_node_types:
                    return self.is_async(child)
            return False
        # `async def foo(...)` — tree-sitter-python emits an "async" anonymous
        # child token before the "def" keyword inside function_definition.
        for child in node.children:
            if child.type == "async":
                return True
        return False

    def module_path_from_file(self, repo_relative_path: str) -> str:
        """src/flask/app.py → flask.app
        flask/__init__.py → flask
        tests/test_app.py → tests.test_app
        """
        p = PurePosixPath(repo_relative_path)
        parts = list(p.parts)
        # Strip common package roots
        if parts and parts[0] in {"src", "lib"}:
            parts = parts[1:]
        # Drop .py suffix from last component
        if parts and parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        # Drop __init__ from path
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts) if parts else p.stem


def _dotted_name_text(node: Node) -> str:
    """Concatenate identifier children with dots."""
    parts: list[str] = []
    for c in node.named_children:
        if c.type == "identifier" and c.text is not None:
            parts.append(c.text.decode("utf-8", errors="replace"))
    return ".".join(parts) if parts else (
        node.text.decode("utf-8", errors="replace") if node.text else ""
    )


def _extract_call_name(node: Node) -> str:
    """Pull a usable callable name out of various expression node types."""
    if node.text is None:
        return ""
    if node.type == "identifier":
        return node.text.decode("utf-8", errors="replace")
    if node.type == "attribute":
        attr = node.child_by_field_name("attribute")
        if attr is not None and attr.text is not None:
            return attr.text.decode("utf-8", errors="replace")
        return node.text.decode("utf-8", errors="replace")
    if node.type == "call":
        func = node.child_by_field_name("function")
        if func is not None:
            return _extract_call_name(func)
    return ""


def _string_text(node: Node) -> str:
    """Strip surrounding quotes from a tree-sitter string node."""
    if node.text is None:
        return ""
    raw = node.text.decode("utf-8", errors="replace")
    for q in ('"""', "'''", '"', "'"):
        if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
            return raw[len(q):-len(q)].strip()
    return raw.strip()
