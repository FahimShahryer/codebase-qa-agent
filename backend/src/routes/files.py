"""GET /files — repo-rooted file slice with skip-list enforcement.

Powers the frontend's citation panel: click `[path:lines]` → fetch this
endpoint → render with syntax highlighting.

Mirrors `tools.read_file` but in HTTP form. Skip-list ensures we never
expose binaries, secrets, or paths outside the indexed repo.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import settings
from src.detect import BINARY_EXTENSIONS, is_secret_filename

router = APIRouter()

REPOS_ROOT = Path("/app/repos")

_LANG_MAP: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".rs": "rust", ".go": "go", ".java": "java",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".cs": "csharp", ".scala": "scala",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss",
    ".md": "markdown", ".rst": "restructuredtext", ".txt": "text",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".sql": "sql", ".xml": "xml",
    ".dockerfile": "dockerfile",
}


class FileSlice(BaseModel):
    path: str
    start: int
    end: int
    total_lines: int
    language: str
    content: str


def _detect_language(path: str) -> str:
    p = Path(path)
    if p.name.lower() == "dockerfile":
        return "dockerfile"
    return _LANG_MAP.get(p.suffix.lower(), "text")


@router.get("/files")
async def read_file_slice(
    path: str,
    start: int = 1,
    end: int = 0,
    repo: str | None = None,
) -> FileSlice:
    """Read a slice of a repo file. start/end are 1-indexed inclusive; end=0=EOF."""
    if not path:
        raise HTTPException(400, "missing 'path' query parameter")

    repo_name = (repo or settings.REPO_NAME).strip()
    if not repo_name:
        raise HTTPException(400, "no repo configured")

    fname = Path(path).name
    if fname.startswith(".") or is_secret_filename(fname):
        raise HTTPException(400, f"refused: '{path}' looks like a secret/hidden file")
    if Path(path).suffix.lower() in BINARY_EXTENSIONS:
        raise HTTPException(400, f"refused: '{path}' is a binary file")

    repo_root = (REPOS_ROOT / repo_name).resolve()
    target = (repo_root / path).resolve()
    try:
        target.relative_to(repo_root)
    except ValueError:
        raise HTTPException(400, f"refused: '{path}' is outside the indexed repo")

    if not target.is_file():
        raise HTTPException(404, f"file not found: {path}")

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(500, f"read error: {e!s}")

    all_lines = text.splitlines()
    total = len(all_lines)
    s = max(1, int(start))
    e = int(end) if end and end > 0 else total
    e = min(e, total)
    if s > e:
        raise HTTPException(400, f"invalid range: start={s} > end={e}")

    return FileSlice(
        path=path,
        start=s,
        end=e,
        total_lines=total,
        language=_detect_language(path),
        content="\n".join(all_lines[s - 1:e]),
    )
