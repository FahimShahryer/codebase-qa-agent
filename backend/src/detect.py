"""Walk a repository, classify files, apply skip-list.

Inspired by graphify/detect.py — directories that never contain project source
we want to index, plus aggressive secret / binary exclusion.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SKIP_DIRS: set[str] = {
    "venv", ".venv", "env", ".env",
    "node_modules", "__pycache__", ".git", ".hg", ".svn",
    "dist", "build", "target", "out", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".eggs",
    ".idea", ".vscode",
}

SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\.env(\..*)?$"),
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"\.crt$"),
    re.compile(r"^id_rsa"),
    re.compile(r"^id_ed25519"),
    re.compile(r"^\.htpasswd$"),
    re.compile(r"^credentials(\.json)?$"),
]

BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
    ".pdf", ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".pyc", ".pyo", ".o", ".a", ".class", ".jar",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3",
    ".npy", ".npz", ".pkl", ".pt", ".pth", ".safetensors",
}

CODE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
}

DOC_EXTENSIONS: dict[str, str] = {
    ".md": "markdown",
    ".rst": "rst",
}

TEST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|/)tests?/"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"_test\.py$"),
    re.compile(r"(^|/)conftest\.py$"),
]


@dataclass
class DiscoveredFile:
    path: Path             # absolute path
    repo_relative: str     # POSIX relative path from repo root
    language: str          # "python" | "markdown" | "rst"
    is_test: bool


def is_test_path(rel_path: str) -> bool:
    return any(p.search(rel_path) for p in TEST_PATTERNS)


def is_secret_filename(name: str) -> bool:
    return any(p.search(name) for p in SECRET_PATTERNS)


def should_skip_dir(name: str) -> bool:
    if name in SKIP_DIRS:
        return True
    if name.startswith("."):
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def classify(filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return None
    if ext in CODE_EXTENSIONS:
        return CODE_EXTENSIONS[ext]
    if ext in DOC_EXTENSIONS:
        return DOC_EXTENSIONS[ext]
    return None


def walk_repo(repo_root: Path) -> Iterator[DiscoveredFile]:
    """Yield files of interest from the repo, skipping noise."""
    repo_root = repo_root.resolve()
    if not repo_root.is_dir():
        raise ValueError(f"Not a directory: {repo_root}")

    for dirpath_s, dirnames, filenames in os.walk(repo_root, topdown=True):
        # Prune skip-dirs in place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        dirpath = Path(dirpath_s)
        for fname in filenames:
            if fname.startswith("."):
                continue
            if is_secret_filename(fname):
                continue
            lang = classify(fname)
            if lang is None:
                continue
            abs_path = dirpath / fname
            try:
                rel = abs_path.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            yield DiscoveredFile(
                path=abs_path,
                repo_relative=rel,
                language=lang,
                is_test=is_test_path(rel),
            )
