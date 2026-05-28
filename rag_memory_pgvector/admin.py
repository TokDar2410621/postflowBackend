"""Admin for RAG memory chunks.

Memory rows are typically created via the indexer (not the admin), but the
admin is invaluable for:

  * Inspecting what got indexed (paste an article, did it chunk sensibly?)
  * Manually injecting "manual note" or "decision" rows that override
    automated content (e.g. brand voice rules, do-not-link domains).
  * Investigating retrieval quality — which chunks have positive vs negative
    feedback_score over time.

This module tries ``unfold.admin.ModelAdmin`` if django-unfold is installed;
otherwise it falls back to stock ``admin.ModelAdmin``.
"""
from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import Memory


@admin.register(Memory)
class MemoryAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "tenant",
        "kind",
        "title_short",
        "source_ref",
        "token_count",
        "feedback_score",
        "created_at",
    )
    list_filter = ("kind",)
    search_fields = ("title", "content", "source_ref", "content_hash")
    readonly_fields = (
        "content_hash",
        "token_count",
        "feedback_score",
        "created_at",
        "updated_at",
        "embedding_status",
    )
    fieldsets = (
        (None, {
            "fields": ("tenant", "kind", "title", "source_ref"),
        }),
        ("Content", {
            "fields": ("content", "metadata"),
        }),
        ("Embedding & stats", {
            "fields": (
                "embedding_status",
                "content_hash",
                "token_count",
                "feedback_score",
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )
    ordering = ("-created_at",)

    @admin.display(description="Title", ordering="title")
    def title_short(self, obj: Memory) -> str:
        if obj.title:
            return obj.title[:60]
        body = (obj.content or "")[:60]
        return f"({body}...)" if body else "(empty)"

    @admin.display(description="Has embedding?")
    def embedding_status(self, obj: Memory) -> str:
        if obj.embedding is None:
            return format_html(
                '<span style="color:#c00;">No embedding (re-index needed)</span>'
            )
        return format_html(
            '<span style="color:#080;">Embedded</span>',
        )
