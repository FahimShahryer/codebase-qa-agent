# syntax=docker/dockerfile:1.7
# BuildKit RUN --mount=type=cache requires the syntax directive above.

FROM python:3.11-slim

# Install uv from the official image (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# ── Layer 1: install deps (cached unless pyproject.toml changes) ──────
# Stub package skeleton so `pip install -e .` succeeds before real
# source is copied. Source goes in a later layer so code edits don't
# invalidate this expensive install.
COPY pyproject.toml ./
RUN mkdir -p src && touch src/__init__.py

# BuildKit cache mounts: uv's wheel cache + pip's wheel cache both
# survive across builds. Even when pyproject.toml changes and the layer
# rebuilds, already-downloaded wheels (torch, sentence-transformers,
# etc.) are reused from cache — only new/upgraded packages download.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    uv pip install --system -e .

# ── Layer 2: source (changes here only rebuild this tiny ~200 kB layer) ──
COPY src/ ./src/

ENV PYTHONPATH=/app

EXPOSE 8000

# --reload watches the bind-mounted src/ for changes during development
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
