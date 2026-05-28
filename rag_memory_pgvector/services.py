"""Service layer — index, re-index, purge, feedback.

These are the write-path entrypoints. Read-path lives in ``selectors.py``.

Idempotency: ``index_text`` is safe to re-run on unchanged content (skips
re-embedding via ``content_hash``). Editing one paragraph in a long article
re-embeds only that chunk, not the whole article — important for cost.
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.db import transaction
from django.db.models import F

from .chunking import chunk_markdown, chunk_text
from .embeddings import (
    EmbeddingError,
    content_hash,
    embed_batch,
    estimate_tokens,
)
from .models import Memory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_text(
    tenant,
    *,
    kind: str,
    content: str,
    source_ref: str = "",
    title: str = "",
    metadata: dict | None = None,
    chunker: str = "markdown",
) -> dict:
    """Chunk + embed + upsert ``Memory`` rows for one source.

    Idempotent: deletes prior rows for ``(tenant, kind, source_ref)`` whose
    content_hash is no longer in the new chunk set, reuses (without
    re-embedding) rows whose hash IS still present, and creates+embeds new
    chunks. Caller passes ``content=""`` to wipe an entire source.

    Args:
        tenant: tenant instance (the FK target of ``Memory.tenant``).
        kind: one of ``RAG_MEMORY_KINDS`` (or your custom kinds).
        content: the source text to chunk + index.
        source_ref: opaque pointer back to the upstream source. Multiple
            ``index_text`` calls with the same ``(tenant, kind, source_ref)``
            mutate the same set of chunks.
        title: optional title carried onto chunks that have no markdown
            heading of their own.
        metadata: caller-defined dict stored as JSON on every chunk.
        chunker: ``"markdown"`` (heading-aware, default) or ``"text"`` (plain
            paragraph windows).

    Returns:
        dict with keys ``created``, ``reused``, ``skipped_empty`` (and
        ``error`` on provider failure).
    """
    metadata = metadata or {}
    content = (content or "").strip()

    # Empty content -> wipe and return.
    if not content:
        deleted = Memory.objects.filter(
            tenant=tenant, kind=kind, source_ref=source_ref,
        ).delete()
        logger.info(
            "rag_memory.wiped tenant=%s kind=%s source_ref=%s deleted=%s",
            getattr(tenant, "pk", tenant), kind, source_ref, deleted[0],
        )
        return {
            "created": 0,
            "reused": 0,
            "deleted": deleted[0],
            "skipped_empty": True,
        }

    if chunker == "markdown":
        chunks = chunk_markdown(content)
    elif chunker == "text":
        chunks = chunk_text(content)
    else:
        raise ValueError(f"Unknown chunker {chunker!r} (use 'markdown' or 'text')")
    if not chunks:
        return {"created": 0, "reused": 0, "skipped_empty": True}

    return _upsert_chunks(
        tenant=tenant,
        kind=kind,
        chunks=chunks,
        source_ref=source_ref,
        default_title=title,
        metadata=metadata,
    )


def index_chunk(
    tenant,
    *,
    kind: str,
    content: str,
    title: str = "",
    source_ref: str = "",
    metadata: dict | None = None,
) -> dict:
    """Index a single pre-chunked piece of text (no chunking applied).

    Use this when YOU control how content is split (e.g. you're indexing
    individual Q/A pairs, individual tickets, etc.) and want one Memory row
    per call.
    """
    metadata = metadata or {}
    content = (content or "").strip()
    if not content:
        return {"created": 0, "reused": 0, "skipped_empty": True}
    return _upsert_chunks(
        tenant=tenant,
        kind=kind,
        chunks=[(title, content)],
        source_ref=source_ref,
        default_title=title,
        metadata=metadata,
    )


def _upsert_chunks(
    *,
    tenant,
    kind: str,
    chunks: list[tuple[str, str]],
    source_ref: str,
    default_title: str,
    metadata: dict,
) -> dict:
    """Shared upsert path used by both ``index_text`` and ``index_chunk``."""
    hashes = [content_hash(body) for _, body in chunks]

    existing = {
        m.content_hash: m
        for m in Memory.objects.filter(
            tenant=tenant,
            kind=kind,
            source_ref=source_ref,
            content_hash__in=hashes,
        )
    }

    # Decide which chunks need a fresh embedding.
    to_embed_idx = [i for i, h in enumerate(hashes) if h not in existing]
    to_embed_texts = [chunks[i][1] for i in to_embed_idx]

    new_embeddings: list[list[float]] = []
    if to_embed_texts:
        try:
            new_embeddings = embed_batch(to_embed_texts, input_type="document")
        except EmbeddingError as e:
            logger.warning(
                "rag_memory.index_failed tenant=%s kind=%s err=%s",
                getattr(tenant, "pk", tenant), kind, e,
            )
            return {"created": 0, "reused": 0, "error": str(e)}

    with transaction.atomic():
        # Wipe stale chunks (rows that no longer have a matching hash) for
        # this source so we don't accumulate orphans when the source shrank.
        Memory.objects.filter(
            tenant=tenant, kind=kind, source_ref=source_ref,
        ).exclude(content_hash__in=hashes).delete()

        created = 0
        reused = 0
        embed_iter = iter(new_embeddings)
        for (chunk_title, body), h in zip(chunks, hashes):
            resolved_title = chunk_title or default_title
            if h in existing:
                # Update non-embedding fields in case title/metadata changed.
                row = existing[h]
                changed = False
                if row.title != resolved_title:
                    row.title = resolved_title
                    changed = True
                if row.metadata != metadata:
                    row.metadata = metadata
                    changed = True
                if changed:
                    row.save(update_fields=["title", "metadata", "updated_at"])
                reused += 1
                continue
            embedding = next(embed_iter, None)
            if embedding is None:
                continue
            Memory.objects.create(
                tenant=tenant,
                kind=kind,
                title=resolved_title,
                content=body,
                embedding=embedding,
                source_ref=source_ref,
                content_hash=h,
                token_count=estimate_tokens(body),
                metadata=metadata,
            )
            created += 1

    logger.info(
        "rag_memory.indexed tenant=%s kind=%s source_ref=%s created=%d reused=%d",
        getattr(tenant, "pk", tenant), kind, source_ref, created, reused,
    )
    return {"created": created, "reused": reused, "skipped_empty": False}


# ---------------------------------------------------------------------------
# Source-level purge (used when an upstream source is deleted entirely)
# ---------------------------------------------------------------------------

def purge_by_source_ref(tenant, *, kind: str | None = None, source_ref: str) -> int:
    """Delete every chunk that points back at ``source_ref``.

    Returns the number of rows deleted. If ``kind`` is None, purges across
    kinds (useful when source_ref is unique across kinds for a tenant).
    """
    qs = Memory.objects.filter(tenant=tenant, source_ref=source_ref)
    if kind is not None:
        qs = qs.filter(kind=kind)
    n, _ = qs.delete()
    logger.info(
        "rag_memory.purged tenant=%s kind=%s source_ref=%s deleted=%d",
        getattr(tenant, "pk", tenant), kind, source_ref, n,
    )
    return n


# ---------------------------------------------------------------------------
# Feedback loop — bumps feedback_score so good chunks float up over time.
# ---------------------------------------------------------------------------

# Hard cap on absolute feedback_score per row. With the ±0.01 multiplier at
# retrieval and the ±0.5 clamp, a score of 50 already saturates the clamp;
# we cap at 100 to leave headroom for visualization without further effect.
FEEDBACK_SCORE_CAP = 100


def mark_used(memory_ids: Iterable[int], rating: int) -> int:
    """Adjust ``feedback_score`` for a batch of memory rows.

    Args:
        memory_ids: iterable of ``Memory.pk``.
        rating: any integer. Use +1 for "this chunk helped" / -1 for "didn't
            help". Callers can also pass larger values for stronger signals
            (e.g. +3 for a user that explicitly upvoted), bounded by
            ``FEEDBACK_SCORE_CAP``.

    Returns:
        Number of rows actually updated.

    Notes:
        We clamp to ``±FEEDBACK_SCORE_CAP`` AFTER the increment so a runaway
        +1 every retrieval doesn't drift to infinity.
    """
    ids = list(memory_ids)
    if not ids or rating == 0:
        return 0
    with transaction.atomic():
        Memory.objects.filter(pk__in=ids).update(
            feedback_score=F("feedback_score") + rating,
        )
        # Clamp.
        Memory.objects.filter(
            pk__in=ids, feedback_score__gt=FEEDBACK_SCORE_CAP,
        ).update(feedback_score=FEEDBACK_SCORE_CAP)
        Memory.objects.filter(
            pk__in=ids, feedback_score__lt=-FEEDBACK_SCORE_CAP,
        ).update(feedback_score=-FEEDBACK_SCORE_CAP)
    logger.info(
        "rag_memory.feedback ids=%s rating=%+d", ids, rating,
    )
    return len(ids)
