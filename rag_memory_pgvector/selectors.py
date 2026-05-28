"""Read-only queries — top-k retrieval + helpers.

The retriever is the hot path: every Claude/LLM call that wants memory hits
this. Implementation:

  1. Embed the query as ``input_type="query"`` (Voyage uses asymmetric
     encoding — query embeddings differ from document embeddings for the
     same text, on purpose).
  2. Cosine-distance order against the ``embedding`` column.
  3. Subtract ``feedback_score * 0.01`` from the distance (lower = better)
     and ORDER BY that adjusted distance. The clamp is enforced through the
     ``FEEDBACK_SCORE_CAP`` set in services.py (capped at ±100 → ±1.0 raw
     effect, but the cosine distance itself stays in ~[0, 2] so practical
     impact is ~±0.5).
  4. Return a list of plain dicts (not querysets) — callers serialize them
     into prompts, so they shouldn't have to know about Django models.
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings

from .embeddings import EmbeddingError, embed_text
from .models import Memory

logger = logging.getLogger(__name__)


def _top_k_default() -> int:
    return int(getattr(settings, "RAG_TOP_K_DEFAULT", 8))


def retrieve_top_k(
    tenant,
    query: str,
    *,
    k: int | None = None,
    kinds: Iterable[str] | None = None,
) -> list[dict]:
    """Top-k nearest memory chunks to ``query`` for this tenant.

    Returns a list of dicts:

        {
            "id":             int,           # row pk
            "kind":           str,
            "title":          str,
            "content":        str,
            "source_ref":     str,
            "distance":       float | None,  # raw cosine distance
            "score":          float | None,  # 1.0 - distance, for convenience
            "feedback_score": int,
        }

    On embedding-provider failure (missing key, network error…) this returns
    ``[]`` and logs a warning rather than raising — callers can fall back to
    keyword search or skip the memory block entirely.
    """
    from django.db.models import ExpressionWrapper, F, FloatField
    from pgvector.django import CosineDistance

    query = (query or "").strip()
    if not query:
        return []
    k = k or _top_k_default()

    try:
        q_embedding = embed_text(query, input_type="query")
    except EmbeddingError as e:
        logger.warning(
            "rag_memory.retrieve_skipped tenant=%s err=%s",
            getattr(tenant, "pk", tenant), e,
        )
        return []

    qs = Memory.objects.filter(tenant=tenant, embedding__isnull=False)
    if kinds:
        qs = qs.filter(kind__in=list(kinds))

    # adjusted_distance = cosine_distance - feedback_score * 0.01
    # Lower = better, so we SUBTRACT the boost. The score cap in services.py
    # (FEEDBACK_SCORE_CAP=100) bounds the practical effect to ~±0.5 on a
    # cosine distance that lives in [0, 2].
    qs = qs.annotate(
        distance=CosineDistance("embedding", q_embedding),
    ).annotate(
        adjusted_distance=ExpressionWrapper(
            F("distance") - F("feedback_score") * 0.01,
            output_field=FloatField(),
        ),
    ).order_by("adjusted_distance")[:k]

    out: list[dict] = []
    for m in qs:
        d = float(m.distance) if m.distance is not None else None
        out.append({
            "id": m.id,
            "kind": m.kind,
            "title": m.title,
            "content": m.content,
            "source_ref": m.source_ref,
            "distance": d,
            "score": (1.0 - d) if d is not None else None,
            "feedback_score": m.feedback_score,
        })
    return out


def list_for_tenant(
    tenant,
    *,
    kinds: Iterable[str] | None = None,
    source_ref: str | None = None,
) -> list[Memory]:
    """All memory rows for a tenant, optionally filtered by kind/source_ref.

    Useful for admin views and bulk operations. NOT for the retrieval hot
    path — use ``retrieve_top_k`` there.
    """
    qs = Memory.objects.filter(tenant=tenant)
    if kinds:
        qs = qs.filter(kind__in=list(kinds))
    if source_ref is not None:
        qs = qs.filter(source_ref=source_ref)
    return list(qs.order_by("-created_at"))


def count_for_tenant(
    tenant,
    *,
    kinds: Iterable[str] | None = None,
) -> int:
    qs = Memory.objects.filter(tenant=tenant)
    if kinds:
        qs = qs.filter(kind__in=list(kinds))
    return qs.count()
