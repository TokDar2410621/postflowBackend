"""LinkedIn published posts -> RAG memory indexer.

Indexes each user's ``PublishedPost`` rows into ``rag_memory_pgvector`` with a
``feedback_score`` derived from engagement (likes, comments, views) weighted
by recency. Re-runs are idempotent: unchanged content short-circuits the
embedding call, and scores are re-SET every run from current stats — so this
is also the right entrypoint to refresh scores after an analytics sync.

Score formula
-------------
score = (engagement_signal + reach_signal) * recency_weight, clamped to ±100.

    engagement_signal = log(likes+1) + 2*log(comments+1)
        Comments cost more attention than likes, so they weigh 2x.
    reach_signal      = log((views+1) / user_baseline) * 10
        Compares each post's reach to the user's median views. A 500-view
        post on a 50-view-baseline user scores high; the same post on a
        5000-view-baseline user scores low. Per-user calibration avoids
        absolute thresholds that mean nothing across audience sizes.
    recency_weight    = exp(-days_old / 60)
        Half-life of 60 days. A 6-month-old post weighs ~5% of a fresh
        one — hedges against LinkedIn algorithm drift.
"""
from __future__ import annotations

import logging
from math import exp, log

from django.utils import timezone

from rag_memory_pgvector.models import Memory
from rag_memory_pgvector.services import index_chunk

from .models import PublishedPost

logger = logging.getLogger(__name__)

RAG_KIND = "past_post"
SCORE_CAP = 100
RECENCY_HALF_LIFE_DAYS = 60.0
MIN_VIEWS_FOR_SCORING = 30


def compute_baseline_views(user) -> int:
    """Median views across this user's published posts. Used as the
    user-specific reach baseline so reach_signal is comparable across very
    different audience sizes.
    """
    views = list(
        PublishedPost.objects.filter(user=user, views__gt=0)
        .values_list("views", flat=True)
    )
    if not views:
        return 200
    views.sort()
    return max(1, views[len(views) // 2])


def compute_feedback_score(post: PublishedPost, baseline_views: int) -> int:
    """Map a post's engagement to a signed score in [-SCORE_CAP, SCORE_CAP]."""
    if post.views < MIN_VIEWS_FOR_SCORING:
        return 0

    days_old = max(0, (timezone.now() - post.published_at).days)
    recency_weight = exp(-days_old / RECENCY_HALF_LIFE_DAYS)

    engagement_signal = log(post.likes + 1) + 2 * log(post.comments + 1)
    reach_signal = log((post.views + 1) / max(baseline_views, 1)) * 10

    raw = (engagement_signal + reach_signal) * recency_weight
    return int(max(-SCORE_CAP, min(SCORE_CAP, raw)))


def _set_feedback_score(memory_ids: list[int], score: int) -> int:
    if not memory_ids:
        return 0
    return Memory.objects.filter(pk__in=memory_ids).update(feedback_score=score)


def index_published_post(post: PublishedPost, baseline_views: int) -> dict:
    """Index ONE PublishedPost into the RAG memory store.

    Idempotent — re-running on unchanged content reuses the existing
    embedding. The feedback_score is always SET (not incremented) from
    current stats, so this doubles as a score sync entrypoint.
    """
    if not post.user_id:
        return {"created": 0, "reused": 0, "skipped_no_user": True}
    if not post.content.strip():
        return {"created": 0, "reused": 0, "skipped_empty": True}

    source_ref = (
        f"linkedin:post:{post.linkedin_post_id}"
        if post.linkedin_post_id
        else f"published_post:{post.pk}"
    )

    result = index_chunk(
        tenant=post.user,
        kind=RAG_KIND,
        content=post.content,
        title=f"LinkedIn post — {post.published_at:%Y-%m-%d}",
        source_ref=source_ref,
        metadata={
            "linkedin_post_id": post.linkedin_post_id,
            "likes": post.likes,
            "comments": post.comments,
            "views": post.views,
            "shares": post.shares,
            "tone": post.tone,
            "has_images": post.has_images,
            "published_at": post.published_at.isoformat(),
            "published_post_pk": post.pk,
        },
    )

    score = compute_feedback_score(post, baseline_views)
    memory_ids = list(
        Memory.objects.filter(
            tenant=post.user, kind=RAG_KIND, source_ref=source_ref,
        ).values_list("pk", flat=True)
    )
    if memory_ids:
        _set_feedback_score(memory_ids, score)
        result["feedback_score"] = score
        result["memory_ids"] = memory_ids

    return result


def safe_index_published_post(post: PublishedPost) -> None:
    """Best-effort indexing after a fresh publish.

    Swallows exceptions so the publish hot path never breaks on a RAG error.
    Baseline is computed from the user's prior posts; a brand-new post has
    no stats yet so its score will be 0 (neutral) — the daily stats sync
    will pick it up and rescore it later.
    """
    try:
        baseline = compute_baseline_views(post.user)
        index_published_post(post, baseline)
    except Exception as e:
        logger.warning(
            "linkedin_rag.auto_index_failed post_pk=%s err=%s", post.pk, e,
        )


def sync_user_posts_to_rag(user) -> dict:
    """Re-index every PublishedPost for one user and refresh feedback_scores.

    Safe to call repeatedly. Use after ``update_all_post_stats()`` so RAG
    retrieval sees fresh engagement signals.
    """
    posts = PublishedPost.objects.filter(user=user).order_by("-published_at")
    baseline = compute_baseline_views(user)

    totals = {
        "created": 0,
        "reused": 0,
        "errors": 0,
        "scored": 0,
        "baseline_views": baseline,
        "total_posts": posts.count(),
    }
    for post in posts:
        try:
            r = index_published_post(post, baseline)
            totals["created"] += r.get("created", 0)
            totals["reused"] += r.get("reused", 0)
            if "feedback_score" in r:
                totals["scored"] += 1
        except Exception as e:
            logger.exception(
                "linkedin_rag.index_failed post_pk=%s err=%s", post.pk, e,
            )
            totals["errors"] += 1

    logger.info("linkedin_rag.synced user=%s totals=%s", user.pk, totals)
    return totals
