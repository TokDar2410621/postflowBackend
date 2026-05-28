"""Glue between the API generation flow and the RAG memory layer.

Two responsibilities:

1. ``build_rag_context(user, query)`` — fetches top-k memories for the user,
   formats them into a system-prompt block, and returns the text + the IDs
   of memories that contributed (so the caller can later mark_used on
   feedback).

2. ``should_explore()`` — epsilon-greedy gate that returns True with
   ``RAG_EXPLORATION_EPSILON`` probability. When True, the caller should
   SKIP injecting the learned_rule / anti_pattern memories so Claude
   generates without the constraints it has learned — that's how we escape
   the convergence trap. Past_post and brand_voice memories are still
   injected, because losing them would degrade the basic voice match.
"""
from __future__ import annotations

import logging
import random

from django.conf import settings

from rag_memory_pgvector.selectors import retrieve_top_k

logger = logging.getLogger(__name__)

# Probability that a single generation will EXPLORE (skip learned rules).
# 0.20 means roughly 1 in 5 posts ignores learned patterns — enough to
# discover new winning styles, not enough to feel inconsistent.
EXPLORATION_EPSILON = float(getattr(settings, "RAG_EXPLORATION_EPSILON", 0.20))

# Kinds always retrieved (the "voice" layer).
VOICE_KINDS = ("brand_voice", "past_post", "decision", "manual", "audience")

# Kinds suppressed during exploration runs.
RULE_KINDS = ("learned_rule", "anti_pattern")


def should_explore() -> bool:
    """Returns True with probability EXPLORATION_EPSILON.

    When True, the caller skips learned_rule / anti_pattern retrieval —
    the generation is intentionally unconstrained so we can discover new
    winning styles (and learn from their performance later).
    """
    return random.random() < EXPLORATION_EPSILON


def build_rag_context(user, query: str, *, k: int = 8) -> tuple[str, list[int], bool]:
    """Retrieve user memories and format a prompt-ready block.

    Returns a tuple of:
        (formatted_text, contributing_memory_ids, exploring)

    formatted_text is empty when retrieval finds nothing or fails — callers
    should append it conditionally. contributing_memory_ids can be passed
    later to ``rag_memory_pgvector.services.mark_used`` if the user signals
    satisfaction with the generation.

    Graceful degradation: any exception is logged and an empty result is
    returned — the generation flow never breaks because of RAG.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return "", [], False
    if not query.strip():
        return "", [], False

    exploring = should_explore()
    allowed_kinds = VOICE_KINDS if exploring else VOICE_KINDS + RULE_KINDS

    try:
        chunks = retrieve_top_k(
            tenant=user, query=query, k=k, kinds=allowed_kinds,
        )
    except Exception as e:
        logger.warning("rag_helpers.retrieve_failed user=%s err=%s", user.pk, e)
        return "", [], exploring

    if not chunks:
        return "", [], exploring

    lines = [
        "## MÉMOIRE UTILISATEUR (référence pour le ton, les sujets, et les règles apprises)",
    ]
    contributing_ids: list[int] = []
    for c in chunks:
        prefix = f"[{c['kind']}]"
        title = f" {c['title']}" if c.get("title") else ""
        lines.append(f"{prefix}{title}\n{c['content']}")
        contributing_ids.append(c["id"])

    if exploring:
        lines.append(
            "## MODE EXPLORATION ACTIVÉ\n"
            "Pour ce post, prends une liberté créative : ne te laisse pas "
            "limiter par les patterns habituels. Essaie un angle, un hook "
            "ou une structure que l'utilisateur n'a pas encore testée."
        )

    return "\n\n".join(lines), contributing_ids, exploring
