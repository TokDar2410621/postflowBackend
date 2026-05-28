"""Embedding provider abstraction for RAG memory.

The provider is a callable resolvable via the ``RAG_EMBEDDING_PROVIDER``
setting. By default it points at the bundled Voyage AI provider
(voyage-3.5-lite, 512 dims via Matryoshka truncation — Anthropic-recommended
for Claude stacks).

Two functions are exposed:

  * ``embed_text(text, input_type="document") -> list[float]``
  * ``embed_batch(texts, input_type="document") -> list[list[float]]``

A provider is just a small object exposing both. To swap to OpenAI:

    # myproj/embeddings_openai.py
    from openai import OpenAI

    def make_provider():
        client = OpenAI()
        def embed_text(text, input_type="document"):
            r = client.embeddings.create(model="text-embedding-3-small", input=text)
            return r.data[0].embedding
        def embed_batch(texts, input_type="document"):
            r = client.embeddings.create(model="text-embedding-3-small", input=texts)
            return [d.embedding for d in r.data]
        return type("Provider", (), {"embed_text": staticmethod(embed_text),
                                      "embed_batch": staticmethod(embed_batch)})()

    # settings.py
    RAG_EMBEDDING_PROVIDER = "myproj.embeddings_openai.make_provider"
    RAG_EMBEDDING_DIMENSIONS = 1536

Tests inject a fake provider via the same hook (see tests/conftest.py).
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Callable, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when the embedding provider call fails or is misconfigured."""


class EmbeddingProvider(Protocol):
    """Duck-typed protocol — anything with these two methods works."""

    def embed_text(self, text: str, input_type: str = "document") -> list[float]: ...
    def embed_batch(
        self, texts: list[str], input_type: str = "document"
    ) -> list[list[float]]: ...


# Module-level cache so we don't reconstruct the provider on every call.
_provider: EmbeddingProvider | None = None


def _resolve_provider() -> EmbeddingProvider:
    """Resolve the configured provider — once per process."""
    global _provider
    if _provider is not None:
        return _provider
    factory_path = getattr(
        settings,
        "RAG_EMBEDDING_PROVIDER",
        "rag_memory_pgvector.embeddings.make_voyage_provider",
    )
    try:
        factory: Callable[[], EmbeddingProvider] = import_string(factory_path)
    except ImportError as e:
        raise EmbeddingError(
            f"RAG_EMBEDDING_PROVIDER not importable ({factory_path}): {e}"
        ) from e
    _provider = factory()
    return _provider


def reset_provider_cache() -> None:
    """Force the next call to re-resolve the provider. Used by tests."""
    global _provider
    _provider = None


def embed_text(text: str, input_type: str = "document") -> list[float]:
    """Embed a single string.

    Use ``input_type="query"`` for retrieval queries — Voyage uses asymmetric
    encoding for better recall. OpenAI ignores the flag, which is fine.
    """
    if not text or not text.strip():
        raise EmbeddingError("Empty text")
    return _resolve_provider().embed_text(text, input_type=input_type)


def embed_batch(
    texts: list[str], input_type: str = "document"
) -> list[list[float]]:
    """Embed many strings. Empty strings get a single-space substitution so
    the provider doesn't reject the batch — callers should filter beforehand."""
    if not texts:
        return []
    safe = [t if (t and t.strip()) else " " for t in texts]
    return _resolve_provider().embed_batch(safe, input_type=input_type)


def content_hash(text: str) -> str:
    """SHA-256 of normalized text. Used to skip re-embedding identical chunks."""
    normalized = " ".join((text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Rough token count — ~4 chars per token for EN/FR.

    Not exact but good enough for budgeting and chunk-size decisions. Override
    by patching this function if you serve heavily non-Latin content.
    """
    return max(1, len(text or "") // 4)


# ---------------------------------------------------------------------------
# Bundled Voyage AI provider (default).
#
# Requires `voyageai>=0.3` and a VOYAGE_API_KEY env var. If you don't want
# Voyage as a dep, swap RAG_EMBEDDING_PROVIDER and uninstall the package.
# ---------------------------------------------------------------------------

VOYAGE_MODEL = "voyage-3.5-lite"
VOYAGE_MAX_BATCH = 64  # API allows 128; stay safe under token caps.


class _VoyageProvider:
    """Thin wrapper around the official ``voyageai`` client."""

    def __init__(self, api_key: str, model: str, output_dim: int):
        try:
            import voyageai  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - optional dep
            raise EmbeddingError(
                "Package voyageai not installed. `pip install voyageai>=0.3`"
            ) from e
        self._client = voyageai.Client(api_key=api_key)
        self._model = model
        self._output_dim = output_dim

    def embed_text(self, text: str, input_type: str = "document") -> list[float]:
        result = self._client.embed(
            texts=[text],
            model=self._model,
            input_type=input_type,
            output_dimension=self._output_dim,
        )
        return result.embeddings[0]

    def embed_batch(
        self, texts: list[str], input_type: str = "document"
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), VOYAGE_MAX_BATCH):
            chunk = texts[i : i + VOYAGE_MAX_BATCH]
            result = self._client.embed(
                texts=chunk,
                model=self._model,
                input_type=input_type,
                output_dimension=self._output_dim,
            )
            out.extend(result.embeddings)
        return out


def make_voyage_provider() -> EmbeddingProvider:
    """Default provider factory — Voyage AI with voyage-3.5-lite @ 512 dims.

    Raises ``EmbeddingError`` (not silently degrading) when ``VOYAGE_API_KEY``
    is missing — callers should catch and decide whether to skip indexing or
    surface a 503.
    """
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise EmbeddingError(
            "VOYAGE_API_KEY env var not set. Set it or swap "
            "RAG_EMBEDDING_PROVIDER to a different provider."
        )
    output_dim = int(getattr(settings, "RAG_EMBEDDING_DIMENSIONS", 512))
    return _VoyageProvider(api_key=api_key, model=VOYAGE_MODEL, output_dim=output_dim)
