"""Shared fixtures for rag_memory_pgvector tests.

We inject a **fake embedding provider** at the ``RAG_EMBEDDING_PROVIDER`` hook
so the tests never call out to Voyage. The fake produces deterministic vectors
based on a hash of the input, so identical inputs yield identical embeddings
(important for the content_hash idempotency test).

Tier note: the retrieval tests require pgvector + Postgres; they're auto-
skipped on SQLite via the ``pgvector_db`` marker fixture.
"""
from __future__ import annotations

import hashlib

import pytest
from django.contrib.auth import get_user_model
from django.db import connection


# ---------------------------------------------------------------------------
# Deterministic fake embedding provider.
# ---------------------------------------------------------------------------

DIMS = 512  # Must match RAG_EMBEDDING_DIMENSIONS in test settings.


def _seeded_vector(text: str, dims: int = DIMS) -> list[float]:
    """Hash-seeded vector — same text → same vector, different text → different
    vector. Small values so the unit-norm assumption from cosine doesn't matter
    for the tests (we're checking shape + idempotency, not retrieval quality)."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Repeat the 32-byte digest until we have ``dims`` floats.
    repeats = (dims // 32) + 1
    raw = (h * repeats)[:dims]
    return [(b / 255.0) - 0.5 for b in raw]


class FakeEmbeddingProvider:
    """Replaces the Voyage provider during tests."""

    calls: list[tuple[str, str]]  # class-level for assertion convenience

    def __init__(self) -> None:
        self.__class__.calls = []

    def embed_text(self, text: str, input_type: str = "document") -> list[float]:
        self.__class__.calls.append((input_type, text))
        return _seeded_vector(text)

    def embed_batch(
        self, texts: list[str], input_type: str = "document"
    ) -> list[list[float]]:
        for t in texts:
            self.__class__.calls.append((input_type, t))
        return [_seeded_vector(t) for t in texts]


def make_fake_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture(autouse=True)
def _fake_provider(settings):
    """Wire the fake provider on every test. Resets the cached provider so
    consecutive tests don't share state."""
    settings.RAG_EMBEDDING_PROVIDER = (
        "rag_memory_pgvector.tests.conftest.make_fake_provider"
    )
    settings.RAG_EMBEDDING_DIMENSIONS = DIMS

    from rag_memory_pgvector import embeddings
    embeddings.reset_provider_cache()
    FakeEmbeddingProvider.calls = []
    yield
    embeddings.reset_provider_cache()


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="ragtest",
        email="ragtest@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def pgvector_db():
    """Skip if the test DB isn't Postgres + pgvector.

    Retrieval relies on the pgvector cosine operator; SQLite can't run it.
    """
    if connection.vendor != "postgresql":
        pytest.skip("Retrieval tests require Postgres with pgvector.")
    yield
