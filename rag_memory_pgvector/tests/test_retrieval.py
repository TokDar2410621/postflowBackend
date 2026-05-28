"""Retrieval tests — pgvector cosine + feedback-score adjustment.

These tests need a real Postgres DB with the pgvector extension. They're
auto-skipped on SQLite via the ``pgvector_db`` fixture.
"""
from __future__ import annotations

import pytest

from rag_memory_pgvector.selectors import (
    count_for_tenant,
    list_for_tenant,
    retrieve_top_k,
)
from rag_memory_pgvector.services import index_text


@pytest.mark.django_db
def test_retrieve_top_k_empty_query_returns_empty(user):
    """Empty queries short-circuit before hitting the provider."""
    assert retrieve_top_k(user, "") == []
    assert retrieve_top_k(user, "   ") == []


@pytest.mark.django_db
def test_retrieve_top_k_handles_embedding_error_gracefully(user, settings):
    """Provider misconfiguration must NOT raise — log + return []."""
    from rag_memory_pgvector import embeddings

    # Point at a broken factory.
    settings.RAG_EMBEDDING_PROVIDER = "rag_memory_pgvector.does_not_exist"
    embeddings.reset_provider_cache()

    result = retrieve_top_k(user, "anything")
    assert result == []


@pytest.mark.django_db
def test_retrieve_top_k_returns_chunks_sorted_by_distance(user, pgvector_db):
    """Smoke retrieval: index a few chunks, query, get them back."""
    index_text(
        user,
        kind="manual",
        content="## Pricing\n\nAll prices are in CAD, taxes included for QC.",
        source_ref="src:pricing",
    )
    index_text(
        user,
        kind="manual",
        content="## Voice\n\nWe never use the formal vous with clients.",
        source_ref="src:voice",
    )
    index_text(
        user,
        kind="manual",
        content="## Competitors\n\nDo not link to Ahrefs or Surfer SEO.",
        source_ref="src:competitors",
    )

    results = retrieve_top_k(user, "what currency for prices", k=3)
    assert len(results) > 0
    # The result dict shape matches what views serialize.
    top = results[0]
    assert set(top.keys()) >= {
        "id", "kind", "title", "content", "source_ref",
        "distance", "score", "feedback_score",
    }
    assert top["distance"] is not None


@pytest.mark.django_db
def test_retrieve_top_k_filters_by_kinds(user, pgvector_db):
    index_text(
        user,
        kind="manual",
        content="Manual note about pricing in CAD.",
        source_ref="src:m1",
    )
    index_text(
        user,
        kind="kb",
        content="KB article about pricing in CAD.",
        source_ref="src:k1",
    )
    results = retrieve_top_k(user, "pricing", k=5, kinds=["kb"])
    assert all(r["kind"] == "kb" for r in results)


@pytest.mark.django_db
def test_list_and_count_for_tenant(user):
    index_text(user, kind="manual", content="A.", source_ref="src:a")
    index_text(user, kind="article", content="B.", source_ref="src:b")
    assert count_for_tenant(user) >= 2
    assert count_for_tenant(user, kinds=["manual"]) >= 1
    rows = list_for_tenant(user, kinds=["article"])
    assert all(r.kind == "article" for r in rows)
