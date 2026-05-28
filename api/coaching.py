"""Coaching API — exposes what the RAG layer has learned about the user's style.

The Pattern Extractor (L2) writes ``learned_rule`` and ``anti_pattern``
memories. This module surfaces them to the frontend so the user can see
WHY their generations look the way they do, and reject rules that don't
feel right (rejection sets feedback_score to -100, drowning the rule out
of future retrievals without deleting the row — useful for diagnostics).
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rag_memory_pgvector.models import Memory

from .linkedin_rag import compute_baseline_views
from .pattern_extractor import (
    ANTI_PATTERN_KIND,
    LEARNED_RULE_KIND,
    MIN_SCORED_POSTS_FOR_EXTRACTION,
)

logger = logging.getLogger(__name__)


def _serialize_rule(memory: Memory) -> dict:
    meta = memory.metadata or {}
    return {
        "id": memory.pk,
        "kind": memory.kind,
        "title": memory.title,
        "content": memory.content,
        "confidence": meta.get("confidence", "medium"),
        "evidence": meta.get("evidence", ""),
        "feedback_score": memory.feedback_score,
        "updated_at": memory.updated_at.isoformat(),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def coaching_rules(request):
    """Return the user's learned writing rules.

    Response shape:
    {
      "winning_patterns": [...],
      "anti_patterns": [...],
      "stats": {
        "scored_posts": N,
        "baseline_views": N,
        "ready_for_extraction": bool,
        "min_required": MIN_SCORED_POSTS_FOR_EXTRACTION
      }
    }
    """
    user = request.user
    winning_qs = Memory.objects.filter(
        tenant=user, kind=LEARNED_RULE_KIND,
    ).order_by("-feedback_score", "-updated_at")
    anti_qs = Memory.objects.filter(
        tenant=user, kind=ANTI_PATTERN_KIND,
    ).order_by("-feedback_score", "-updated_at")

    scored_posts = Memory.objects.filter(
        tenant=user, kind="past_post",
    ).exclude(feedback_score=0).count()

    return Response({
        "winning_patterns": [_serialize_rule(m) for m in winning_qs],
        "anti_patterns": [_serialize_rule(m) for m in anti_qs],
        "stats": {
            "scored_posts": scored_posts,
            "baseline_views": compute_baseline_views(user),
            "ready_for_extraction": scored_posts >= MIN_SCORED_POSTS_FOR_EXTRACTION,
            "min_required": MIN_SCORED_POSTS_FOR_EXTRACTION,
        },
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def coaching_reject_rule(request, pk: int):
    """Reject a learned rule. Sets feedback_score=-100 so the rule is
    drowned out of retrieval without deleting the row (useful for
    diagnostics + lets the next extraction overwrite it cleanly).
    """
    try:
        memory = Memory.objects.get(
            pk=pk, tenant=request.user,
            kind__in=[LEARNED_RULE_KIND, ANTI_PATTERN_KIND],
        )
    except Memory.DoesNotExist:
        return Response(
            {"error": "Rule not found"}, status=status.HTTP_404_NOT_FOUND,
        )
    memory.feedback_score = -100
    memory.save(update_fields=["feedback_score", "updated_at"])
    logger.info("coaching.rule_rejected user=%s memory_pk=%s", request.user.pk, pk)
    return Response({"success": True, "id": pk})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def coaching_confirm_rule(request, pk: int):
    """Re-confirm a previously rejected rule (or just bump it). Resets
    feedback_score to LEARNED_RULE_SCORE (80) so it re-enters retrieval.
    """
    from .pattern_extractor import LEARNED_RULE_SCORE

    try:
        memory = Memory.objects.get(
            pk=pk, tenant=request.user,
            kind__in=[LEARNED_RULE_KIND, ANTI_PATTERN_KIND],
        )
    except Memory.DoesNotExist:
        return Response(
            {"error": "Rule not found"}, status=status.HTTP_404_NOT_FOUND,
        )
    memory.feedback_score = LEARNED_RULE_SCORE
    memory.save(update_fields=["feedback_score", "updated_at"])
    return Response({"success": True, "id": pk})
