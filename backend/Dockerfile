FROM python:3.11-slim

# Install uv from the official image (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install deps from pyproject (cached layer — only re-runs if pyproject changes)
COPY pyproject.toml ./
COPY src/ ./src/
RUN uv pip install --system --no-cache -e .

ENV PYTHONPATH=/app

EXPOSE 8000

# --reload watches the bind-mounted src/ for changes during development
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
