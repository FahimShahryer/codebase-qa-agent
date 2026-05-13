from fastapi import FastAPI

from src.routes import health

app = FastAPI(
    title="Codebase Q&A Agent",
    version="0.1.0",
    description="Agentic Q&A over a public GitHub codebase",
)

# Step 1: only /health is wired. Subsequent steps add /chat, /repos, /sessions,
# /files, /search via the same include_router pattern.
app.include_router(health.router)
