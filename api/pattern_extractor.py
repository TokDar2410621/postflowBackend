"""Pattern extractor (L2 of the learning loop).

For each user with enough scored history, ask Claude to compare their best
and worst LinkedIn posts and distill 5-10 winning patterns + 3-5 anti-patterns.
Output is indexed as RAG memories with high feedback_score, so they float to
the top of every future retrieval — effectively becoming bespoke writing
rules for that user, learned from their own audience's behavior.

Guardrails against hallucinated rules:
  * Claude is required to cite a verbatim excerpt from the post that
    justifies each rule. Rules without evidence are dropped.
  * The model contrasts top vs bottom explicitly — rules present in BOTH
    cohorts are not "differentiators" and must be discarded.
  * Output is parsed as strict JSON; malformed responses are logged and
    skipped (no learned_rule is better than a wrong learned_rule).
  * Re-runs purge prior learned_rule / anti_pattern rows for the user
    before saving new ones — patterns never accumulate stale data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic
from django.conf import settings

from rag_memory_pgvector.models import Memory
from rag_memory_pgvector.services import index_chunk

from .linkedin_rag import RAG_KIND as PAST_POST_KIND

logger = logging.getLogger(__name__)

LEARNED_RULE_KIND = "learned_rule"
ANTI_PATTERN_KIND = "anti_pattern"

# Score that makes learned rules nearly always retrieved (saturates the ±0.5
# cosine clamp in rag_memory_pgvector at retrieval time).
LEARNED_RULE_SCORE = 80

# Eligibility threshold — below this, signal is too thin and Claude will
# either invent patterns or generate trivial ones.
MIN_SCORED_POSTS_FOR_EXTRACTION = 10

# How many top/bottom posts to feed into the contrast prompt.
TOP_N = 5
BOTTOM_N = 5

EXTRACTION_MODEL = "claude-sonnet-4-20250514"


def _eligible_posts(user) -> tuple[list[Memory], list[Memory]]:
    """Return (top_posts, bottom_posts) Memory rows for the user.

    Filters to past_post memories with non-zero feedback_score (i.e. posts
    with enough views to have been scored at all). Top = highest scores,
    bottom = lowest. Empty lists if the user is below threshold.
    """
    scored = list(
        Memory.objects.filter(tenant=user, kind=PAST_POST_KIND)
        .exclude(feedback_score=0)
        .order_by("-feedback_score")
    )
    if len(scored) < MIN_SCORED_POSTS_FOR_EXTRACTION:
        return [], []
    return scored[:TOP_N], scored[-BOTTOM_N:][::-1]


def _format_posts_for_prompt(posts: list[Memory], label: str) -> str:
    if not posts:
        return f"(aucun post dans la catégorie {label})"
    lines = []
    for i, p in enumerate(posts, start=1):
        meta = p.metadata or {}
        stats = (
            f"likes={meta.get('likes', '?')} "
            f"comments={meta.get('comments', '?')} "
            f"views={meta.get('views', '?')}"
        )
        lines.append(
            f"--- {label} #{i} (score={p.feedback_score}, {stats}) ---\n"
            f"{p.content}"
        )
    return "\n\n".join(lines)


def _build_extraction_prompt(top_posts: list[Memory], bottom_posts: list[Memory]) -> str:
    return f"""Tu analyses l'historique LinkedIn d'un créateur de contenu pour identifier ce qui fonctionne et ce qui ne fonctionne pas SPÉCIFIQUEMENT pour SON audience.

POSTS QUI ONT BIEN PERFORMÉ :
{_format_posts_for_prompt(top_posts, "TOP")}

POSTS QUI ONT MAL PERFORMÉ :
{_format_posts_for_prompt(bottom_posts, "BOTTOM")}

Ta tâche :
1. Identifie 5 à 10 **patterns gagnants** : des caractéristiques concrètes (hook, structure, longueur, sujet, ton, format) PRÉSENTES dans les TOP et ABSENTES des BOTTOM.
2. Identifie 3 à 5 **anti-patterns** : des caractéristiques PRÉSENTES dans les BOTTOM et ABSENTES des TOP.

Règles strictes :
- Chaque pattern DOIT être justifié par une citation littérale extraite d'un post (`evidence`). Si tu ne peux pas citer, ne mentionne pas le pattern.
- Rejette les patterns triviaux ("écrire en français", "utiliser des phrases"). Sois spécifique : hook contrarian, listes < 5 items, question en ouverture, etc.
- Si un pattern apparaît dans les DEUX cohortes, ne le mentionne pas (c'est du bruit, pas un différenciateur).
- `confidence` ∈ {{"high", "medium", "low"}} selon la fréquence du pattern dans la cohorte.

Réponds UNIQUEMENT avec un JSON valide, sans texte avant ni après, dans ce format exact :

{{
  "winning_patterns": [
    {{"rule": "Hook contrarian qui démolit une croyance populaire", "evidence": "J'ai refusé une augmentation de 30%. Voici pourquoi.", "confidence": "high"}},
    ...
  ],
  "anti_patterns": [
    {{"rule": "Ouverture avec une expression corporate générique", "evidence": "Ravi de vous annoncer que...", "confidence": "medium"}},
    ...
  ]
}}
"""


def _parse_extraction_response(raw: str) -> dict[str, Any] | None:
    """Strip code fences if any, parse strict JSON. Return None on failure."""
    cleaned = raw.strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers if Claude added them.
    fence_match = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("pattern_extractor.parse_failed err=%s raw=%r", e, raw[:300])
        return None


def _purge_prior_rules(user) -> int:
    """Wipe prior learned_rule + anti_pattern rows for this user.

    Re-runs replace the rule set entirely (no merge), so stale patterns
    from an older audience profile don't linger.
    """
    n, _ = Memory.objects.filter(
        tenant=user, kind__in=[LEARNED_RULE_KIND, ANTI_PATTERN_KIND],
    ).delete()
    return n


def _index_rule(user, kind: str, rule: dict[str, Any], idx: int) -> bool:
    text = (rule.get("rule") or "").strip()
    evidence = (rule.get("evidence") or "").strip()
    if not text or not evidence:
        return False
    confidence = rule.get("confidence", "medium")
    label = "À FAIRE" if kind == LEARNED_RULE_KIND else "À ÉVITER"
    body = (
        f"{label}: {text}\n"
        f"Exemple tiré de tes propres posts : « {evidence} »\n"
        f"Confiance : {confidence}"
    )
    res = index_chunk(
        tenant=user,
        kind=kind,
        content=body,
        title=text[:120],
        source_ref=f"learned:{kind}:{idx}",
        metadata={"confidence": confidence, "evidence": evidence},
    )
    # SET feedback_score so these rules dominate retrieval.
    memory_ids = list(
        Memory.objects.filter(
            tenant=user, kind=kind, source_ref=f"learned:{kind}:{idx}",
        ).values_list("pk", flat=True)
    )
    if memory_ids:
        Memory.objects.filter(pk__in=memory_ids).update(
            feedback_score=LEARNED_RULE_SCORE,
        )
    return res.get("created", 0) > 0 or res.get("reused", 0) > 0


def extract_patterns_for_user(user) -> dict[str, Any]:
    """Run L2 extraction for one user. Idempotent — replaces prior rules."""
    top_posts, bottom_posts = _eligible_posts(user)
    if not top_posts:
        return {
            "skipped": True,
            "reason": (
                f"besoin d'au moins {MIN_SCORED_POSTS_FOR_EXTRACTION} posts scorés"
            ),
        }

    if not settings.ANTHROPIC_API_KEY:
        return {"skipped": True, "reason": "ANTHROPIC_API_KEY not configured"}

    prompt = _build_extraction_prompt(top_posts, bottom_posts)
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        logger.exception("pattern_extractor.api_failed user=%s err=%s", user.pk, e)
        return {"skipped": True, "reason": f"anthropic error: {e}"}

    raw = "".join(
        block.text for block in message.content if hasattr(block, "text")
    )
    parsed = _parse_extraction_response(raw)
    if parsed is None:
        return {"skipped": True, "reason": "Claude returned malformed JSON"}

    _purge_prior_rules(user)

    winning = parsed.get("winning_patterns", []) or []
    anti = parsed.get("anti_patterns", []) or []

    indexed_winning = 0
    for i, rule in enumerate(winning):
        if _index_rule(user, LEARNED_RULE_KIND, rule, idx=i):
            indexed_winning += 1

    indexed_anti = 0
    for i, rule in enumerate(anti):
        if _index_rule(user, ANTI_PATTERN_KIND, rule, idx=i):
            indexed_anti += 1

    logger.info(
        "pattern_extractor.done user=%s winning=%d anti=%d",
        user.pk, indexed_winning, indexed_anti,
    )
    return {
        "skipped": False,
        "winning_patterns_indexed": indexed_winning,
        "anti_patterns_indexed": indexed_anti,
        "top_posts_analyzed": len(top_posts),
        "bottom_posts_analyzed": len(bottom_posts),
    }
