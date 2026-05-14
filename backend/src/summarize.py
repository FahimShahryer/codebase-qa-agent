"""LLM-based chunk summary generation with content-hash cache.

verified: /websites/langchain_oss_python_langchain (May 2026)
- `from langchain.chat_models import init_chat_model` is the canonical V1
  initialiser; accepts "provider:model" strings and forwards extra kwargs
  (api_key, base_url, temperature) to the underlying provider class.

Summaries are deliberately constrained in style (verb-first, factual, no
marketing) so they cluster well in embedding space and serve as good
search targets in their own right (per approach1.md Step 3).
"""
from __future__ import annotations

from langchain.chat_models import init_chat_model
from tenacity import retry, stop_after_attempt, wait_exponential

from src.cache import content_hash, get_summary, set_summary
from src.chunks import Chunk
from src.config import settings


_SENTENCE_TARGET: dict[str, str] = {
    "file": "2-3",
    "class": "2",
    "function": "1-2",
    "method": "1-2",
}

# Cap code excerpts to keep prompts cheap — gpt-4o-mini handles 2-3k tokens
# at ~$0.15/1M input.
_CODE_PREVIEW_CHARS = 2000


def _make_llm():
    """Build the summary LLM via the V1 unified initialiser."""
    provider = settings.SUMMARY_PROVIDER.lower()
    model_str = f"{provider}:{settings.SUMMARY_MODEL}"
    kwargs: dict = {"temperature": 0, "max_retries": 2}
    if provider == "ollama":
        kwargs["base_url"] = settings.OLLAMA_BASE_URL
        kwargs.pop("max_retries", None)  # ChatOllama doesn't accept it
    elif provider == "openai" and settings.OPENAI_API_KEY:
        kwargs["api_key"] = settings.OPENAI_API_KEY
    return init_chat_model(model_str, **kwargs)


def _build_prompt(chunk: Chunk) -> str:
    target = _SENTENCE_TARGET.get(chunk.chunk_type, "1-2")
    sym = chunk.symbol_path or chunk.file_path
    code_preview = chunk.code[:_CODE_PREVIEW_CHARS]
    return (
        f"You are documenting a {chunk.chunk_type} from the "
        f"{settings.REPO_NAME} codebase.\n\n"
        f"File: {chunk.file_path}\n"
        f"Symbol: {sym}\n\n"
        f"{code_preview}\n\n"
        f"Write a {target} sentence factual description of what this "
        f"{chunk.chunk_type} does.\n\n"
        "Rules:\n"
        "- Start with a verb (e.g., \"Parses\", \"Wraps\", \"Stores\")\n"
        "- Be specific about inputs, outputs, side effects\n"
        "- Mention relevant types/classes/external libs by name\n"
        "- Don't invent behaviour not visible in the code\n"
        "- Don't write \"This function...\" — describe behaviour directly\n"
        "- No marketing language (\"efficiently\", \"robust\", \"elegant\")\n"
        "- Output the description only, no prefix, no quotes."
    )


class Summarizer:
    """Provider-agnostic chunk summarizer with transparent caching."""

    def __init__(self) -> None:
        self.provider = settings.SUMMARY_PROVIDER.lower()
        self.model = settings.SUMMARY_MODEL
        self._llm = _make_llm()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=15))
    def _invoke(self, prompt: str) -> str:
        resp = self._llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        return text.strip().strip('"\'')

    def _cache_key(self, chunk: Chunk) -> str:
        # Key on chunk_type + code body so the same code under different
        # symbol paths (rare but possible) gets the same summary, and
        # summaries are invalidated when the body changes.
        return content_hash(f"{chunk.chunk_type}::{chunk.code}")

    def summarize(self, chunk: Chunk) -> tuple[str, bool]:
        """Return (summary, was_cache_hit). Doc/markdown chunks short-circuit."""
        if chunk.chunk_type == "doc":
            return chunk.docstring or "", True
        h = self._cache_key(chunk)
        cached = get_summary(h, self.provider, self.model)
        if cached is not None:
            return cached, True
        summary = self._invoke(_build_prompt(chunk))
        set_summary(h, self.provider, self.model, summary)
        return summary, False
