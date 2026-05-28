"""Feedback-loop tests — mark_used bumps + clamps feedback_score."""
from __future__ import annotations

import pytest

from rag_memory_pgvector.models import Memory
from rag_memory_pgvector.services import (
    FEEDBACK_SCORE_CAP,
    index_text,
    mark_used,
)


@pytest.mark.django_db
def test_mark_used_bumps_feedback_score(user):
    index_text(user, kind="manual", content="One chunk.", source_ref="src:fb1")
    ids = list(Memory.objects.filter(tenant=user).values_list("pk", flat=True))
    assert ids

    updated = mark_used(ids, rating=+1)
    assert updated == len(ids)
    for m in Memory.objects.filter(pk__in=ids):
        assert m.feedback_score == 1

    # Negative rating decrements.
    mark_used(ids, rating=-2)
    for m in Memory.objects.filter(pk__in=ids):
        assert m.feedback_score == -1


@pytest.mark.django_db
def test_mark_used_rating_zero_is_noop(user):
    index_text(user, kind="manual", content="One chunk.", source_ref="src:fb2")
    ids = list(Memory.objects.filter(tenant=user).values_list("pk", flat=True))
    updated = mark_used(ids, rating=0)
    assert updated == 0
    for m in Memory.objects.filter(pk__in=ids):
        assert m.feedback_score == 0


@pytest.mark.django_db
def test_mark_used_empty_ids_is_noop(user):
    assert mark_used([], rating=1) == 0


@pytest.mark.django_db
def test_mark_used_clamps_to_score_cap(user):
    index_text(user, kind="manual", content="Hot chunk.", source_ref="src:fb3")
    ids = list(Memory.objects.filter(tenant=user).values_list("pk", flat=True))

    # Bump enough times to exceed the cap.
    for _ in range(FEEDBACK_SCORE_CAP + 50):
        mark_used(ids, rating=+1)

    for m in Memory.objects.filter(pk__in=ids):
        assert m.feedback_score == FEEDBACK_SCORE_CAP

    # And clamps on the negative side too.
    for _ in range(FEEDBACK_SCORE_CAP * 3):
        mark_used(ids, rating=-1)

    for m in Memory.objects.filter(pk__in=ids):
        assert m.feedback_score == -FEEDBACK_SCORE_CAP
