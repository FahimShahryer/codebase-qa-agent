from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables (.env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ── LLM (answering — wired in Step 7) ───────────────────────────
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:7b"

    # ── Embedding (indexing — wired in Step 4) ──────────────────────
    EMBED_PROVIDER: str = "openai"
    EMBED_MODEL: str = "text-embedding-3-small"

    # ── Summary generation (indexing — wired in Step 4) ─────────────
    SUMMARY_PROVIDER: str = "openai"
    SUMMARY_MODEL: str = "gpt-4o-mini"

    # ── Judge (eval — wired in Step 10) ─────────────────────────────
    JUDGE_PROVIDER: str = "openai"
    JUDGE_MODEL: str = "gpt-4o"

    # ── Reranker (local cross-encoder — wired in Step 6) ────────────
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"

    # ── Weaviate connection (wired in Step 3) ───────────────────────
    WEAVIATE_URL: str = "http://weaviate:8080"
    WEAVIATE_GRPC_PORT: int = 50051

    # ── Repo ────────────────────────────────────────────────────────
    REPO_NAME: str = "flask"
    REPO_PATH: str = "/app/repos/flask"

    # ── Server ──────────────────────────────────────────────────────
    LOG_LEVEL: str = "info"


settings = Settings()
