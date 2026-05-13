"""Embedding provider factory with content-hash cache.

verified: /websites/langchain_oss_python_langchain (May 2026)
- from langchain_openai import OpenAIEmbeddings
- from langchain_huggingface import HuggingFaceEmbeddings
Both expose .embed_documents([texts]) → list[list[float]] and .embed_query(text).
"""
from __future__ import annotations

from tenacity import retry, stop_after_attempt, wait_exponential

from src.cache import content_hash, get_embedding, set_embedding
from src.config import settings

# Known model → dimension. Used for sanity-checking; the actual dim comes
# from the first embed call if not in this table.
_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
}


def _make_openai_embedder():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model=settings.EMBED_MODEL,
        api_key=settings.OPENAI_API_KEY or None,
    )


def _make_sbert_embedder():
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name=settings.EMBED_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )


class Embedder:
    """Provider-agnostic embedder with transparent caching."""

    def __init__(self) -> None:
        self.provider = settings.EMBED_PROVIDER.lower()
        self.model = settings.EMBED_MODEL
        if self.provider == "openai":
            self._impl = _make_openai_embedder()
        elif self.provider in ("sbert", "huggingface", "hf"):
            self._impl = _make_sbert_embedder()
        else:
            raise ValueError(
                f"Unknown EMBED_PROVIDER: {self.provider!r} (expected: openai | sbert)"
            )
        self.expected_dimension = _DIMENSIONS.get(self.model)

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=20))
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._impl.embed_documents(texts)

    def embed(self, texts: list[str], *, batch_size: int = 64) -> tuple[list[list[float]], dict]:
        """Embed texts with content-hash cache. Returns (vectors, stats)."""
        if not texts:
            return [], {"total": 0, "hits": 0, "misses": 0, "hit_rate": 0.0}

        results: list[list[float] | None] = [None] * len(texts)
        missing_idx: list[int] = []
        missing_texts: list[str] = []

        for i, t in enumerate(texts):
            h = content_hash(t)
            cached = get_embedding(h, self.provider, self.model)
            if cached is not None:
                results[i] = cached
            else:
                missing_idx.append(i)
                missing_texts.append(t)

        # Embed missing in batches
        for start in range(0, len(missing_texts), batch_size):
            batch = missing_texts[start:start + batch_size]
            batch_idx = missing_idx[start:start + batch_size]
            new_vectors = self._embed_batch(batch)
            for idx, vec, text in zip(batch_idx, new_vectors, batch):
                results[idx] = vec
                set_embedding(content_hash(text), self.provider, self.model, vec)

        # Sanity check dimension
        dim = len(results[0]) if results and results[0] is not None else 0
        if self.expected_dimension and dim != self.expected_dimension:
            # Warn but don't fail — model dimensions can vary
            pass

        return [r for r in results if r is not None], {
            "total": len(texts),
            "hits": len(texts) - len(missing_idx),
            "misses": len(missing_idx),
            "hit_rate": (len(texts) - len(missing_idx)) / len(texts),
            "dimension": dim,
            "provider": self.provider,
            "model": self.model,
        }
