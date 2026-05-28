"""DRF serializers for the RAG memory API."""
from __future__ import annotations

from rest_framework import serializers

from .models import Memory


class MemorySerializer(serializers.ModelSerializer):
    """Full row serialization — used by admin / listing endpoints."""

    class Meta:
        model = Memory
        fields = (
            "id",
            "tenant",
            "kind",
            "title",
            "content",
            "source_ref",
            "content_hash",
            "token_count",
            "metadata",
            "feedback_score",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "content_hash",
            "token_count",
            "feedback_score",
            "created_at",
            "updated_at",
        )


# ---------------------------------------------------------------------------
# Index endpoint: POST /api/rag/index/
# ---------------------------------------------------------------------------

class IndexRequestSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=32)
    content = serializers.CharField(allow_blank=True)
    title = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    source_ref = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="",
    )
    metadata = serializers.JSONField(required=False, default=dict)
    chunker = serializers.ChoiceField(
        choices=("markdown", "text"), required=False, default="markdown",
    )


class IndexResponseSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    reused = serializers.IntegerField()
    deleted = serializers.IntegerField(required=False)
    skipped_empty = serializers.BooleanField(required=False)
    error = serializers.CharField(required=False)


# ---------------------------------------------------------------------------
# Retrieve endpoint: POST /api/rag/retrieve/
# ---------------------------------------------------------------------------

class RetrieveRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=4000)
    k = serializers.IntegerField(required=False, min_value=1, max_value=50)
    kinds = serializers.ListField(
        child=serializers.CharField(max_length=32),
        required=False,
    )


class RetrievedChunkSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    content = serializers.CharField()
    source_ref = serializers.CharField(allow_blank=True)
    distance = serializers.FloatField(allow_null=True)
    score = serializers.FloatField(allow_null=True)
    feedback_score = serializers.IntegerField()


class RetrieveResponseSerializer(serializers.Serializer):
    results = RetrievedChunkSerializer(many=True)


# ---------------------------------------------------------------------------
# Feedback endpoint: POST /api/rag/feedback/
# ---------------------------------------------------------------------------

class FeedbackRequestSerializer(serializers.Serializer):
    memory_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        help_text="IDs of memory chunks to bump.",
    )
    rating = serializers.IntegerField(
        min_value=-10, max_value=10,
        help_text="+1 for 'helped', -1 for 'didn't help'. Range ±10.",
    )


class FeedbackResponseSerializer(serializers.Serializer):
    updated = serializers.IntegerField()
