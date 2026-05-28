"""Indexer tests — chunking + idempotency + delta re-embedding."""
from __future__ import annotations

import pytest

from rag_memory_pgvector.chunking import chunk_markdown
from rag_memory_pgvector.embeddings import content_hash, estimate_tokens
from rag_memory_pgvector.models import Memory
from rag_memory_pgvector.services import (
    index_chunk,
    index_text,
    purge_by_source_ref,
)
from rag_memory_pgvector.tests.conftest import FakeEmbeddingProvider


# ---------------------------------------------------------------------------
# Pure logic — no DB.
# ---------------------------------------------------------------------------

def test_chunk_markdown_empty_input_returns_empty():
    assert chunk_markdown("") == []
    assert chunk_markdown(None) == []
    assert chunk_markdown("   \n\n  ") == []


def test_chunk_markdown_headings_create_separate_chunks():
    text = (
        "# Intro\n\nIntro body.\n\n"
        "## Section A\n\nBody A.\n\n"
        "## Section B\n\nBody B."
    )
    chunks = chunk_markdown(text)
    assert [t for t, _ in chunks] == ["Intro", "Section A", "Section B"]


def test_chunk_markdown_pre_heading_content_gets_empty_title():
    text = "Floating intro.\n\n## Then a section\n\nContent."
    chunks = chunk_markdown(text)
    assert chunks[0][0] == ""
    assert "Floating intro" in chunks[0][1]
    assert chunks[1][0] == "Then a section"


def test_content_hash_normalizes_whitespace():
    assert content_hash("hello  world\n\nfoo") == content_hash("hello world foo")
    assert content_hash("a") != content_hash("a!")
    h = content_hash("abc")
    assert len(h) == 64
    int(h, 16)  # raises if not hex


def test_estimate_tokens_rough_bounds():
    assert estimate_tokens("") == 1
    assert 10 < estimate_tokens("a" * 100) < 50


# ---------------------------------------------------------------------------
# DB indexer — fake provider, real Django ORM.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_index_text_creates_rows(user):
    result = index_text(
        user,
        kind="manual",
        content="# Title\n\nBody.\n\n## Section\n\nMore body.",
        source_ref="src:1",
        title="Test",
    )
    assert result["created"] == 2
    assert result["reused"] == 0
    assert Memory.objects.filter(tenant=user).count() == 2
    # Provider called exactly once per fresh chunk.
    assert len(FakeEmbeddingProvider.calls) == 2


@pytest.mark.django_db
def test_index_text_idempotent_on_identical_content(user):
    """Same content_hash → no re-embedding, no new rows."""
    content = "# T\n\nUnchanged paragraph."
    index_text(user, kind="manual", content=content, source_ref="src:2")
    first_pass_calls = len(FakeEmbeddingProvider.calls)
    baseline = Memory.objects.filter(tenant=user, source_ref="src:2").count()

    result = index_text(user, kind="manual", content=content, source_ref="src:2")
    assert result["created"] == 0
    assert result["reused"] >= 1
    # Provider NOT called again — saved API spend.
    assert len(FakeEmbeddingProvider.calls) == first_pass_calls
    assert Memory.objects.filter(tenant=user, source_ref="src:2").count() == baseline


@pytest.mark.django_db
def test_index_text_delta_only_embeds_changed_chunks(user):
    v1 = "## A\n\nFirst.\n\n## B\n\nSecond."
    index_text(user, kind="manual", content=v1, source_ref="src:3")
    calls_after_v1 = len(FakeEmbeddingProvider.calls)

    # Mutate only section B.
    v2 = "## A\n\nFirst.\n\n## B\n\nSecond CHANGED."
    result = index_text(user, kind="manual", content=v2, source_ref="src:3")

    assert result["created"] == 1  # Only section B was re-embedded
    assert result["reused"] == 1   # Section A reused
    # Exactly one new embed call (the changed chunk).
    assert len(FakeEmbeddingProvider.calls) - calls_after_v1 == 1


@pytest.mark.django_db
def test_index_text_empty_content_wipes_prior_rows(user):
    index_text(user, kind="manual", content="Some content here.", source_ref="src:wipe")
    assert Memory.objects.filter(tenant=user, source_ref="src:wipe").count() > 0

    result = index_text(user, kind="manual", content="", source_ref="src:wipe")
    assert result["skipped_empty"] is True
    assert Memory.objects.filter(tenant=user, source_ref="src:wipe").count() == 0


@pytest.mark.django_db
def test_index_chunk_creates_single_row_without_chunking(user):
    """A long body that WOULD be split by chunk_markdown stays as one row
    when caller uses index_chunk."""
    long_body = ("This is a paragraph. " * 200).strip()
    result = index_chunk(
        user, kind="kb", content=long_body, title="One row", source_ref="src:single",
    )
    assert result["created"] == 1
    rows = Memory.objects.filter(tenant=user, source_ref="src:single")
    assert rows.count() == 1
    assert rows.first().title == "One row"


@pytest.mark.django_db
def test_purge_by_source_ref_deletes_all_chunks_for_source(user):
    index_text(user, kind="article", content="# A\n\nBody.", source_ref="art:42")
    assert Memory.objects.filter(tenant=user, source_ref="art:42").count() >= 1

    n = purge_by_source_ref(user, kind="article", source_ref="art:42")
    assert n >= 1
    assert Memory.objects.filter(tenant=user, source_ref="art:42").count() == 0


@pytest.mark.django_db
def test_index_text_rejects_unknown_chunker(user):
    with pytest.raises(ValueError):
        index_text(user, kind="manual", content="x", chunker="bogus")
