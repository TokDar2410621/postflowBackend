"""Per-tenant RAG memory store — one row per chunk + pgvector embedding.

Each ``Memory`` row holds:
  * The chunk content + an optional human title (often the markdown heading)
  * A pgvector embedding (default 512 dims = Voyage voyage-3.5-lite Matryoshka)
  * A ``content_hash`` so the indexer can skip re-embedding identical chunks
    when the source is re-indexed (90% no-op on small edits — saves API spend)
  * A ``source_ref`` pointer so the indexer can purge + re-insert all chunks
    that belonged to one source (e.g. a single article slug, audit id, etc.)
  * A ``feedback_score`` (signed integer): +1 every time this chunk contributed
    to a retrieval the caller marked as "good", -1 when marked "bad". The
    retriever subtracts ``feedback_score * 0.01`` from the cosine distance and
    clamps the influence to ±0.5, so a few hot chunks float to the top of
    future retrievals without drowning out semantic match.

The tenant FK target is configurable via ``RAG_TENANT_MODEL`` (defaults to
``settings.AUTH_USER_MODEL``). Set it to e.g. ``"sites.Site"`` or
``"orgs.Workspace"`` to scope memories per-site instead of per-user.

The vector dimension is configurable via ``RAG_EMBEDDING_DIMENSIONS`` and MUST
match what the embedding provider returns — if you swap providers, you must
also create a new migration that updates the ``embedding`` column dimension.

Why a single ``Memory`` model (not separate ChunkSet + Chunk): we never query
sets without their chunks. Keeping it flat speeds retrieval (one indexed
table) and simplifies the feedback loop (bump one row, not a join).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from pgvector.django import VectorField


# ---------------------------------------------------------------------------
# Configurable kinds
#
# The blog-dashboard origin used:
#   ('article', 'kb', 'audit', 'decision', 'manual')
#
# Override per project — the underlying column is just CharField(max_length=32)
# so you can add custom kinds without a migration:
#
#   RAG_MEMORY_KINDS = [
#       ('lesson',   'Cours'),
#       ('faq',      'FAQ'),
#       ('decision', 'Décision'),
#   ]
# ---------------------------------------------------------------------------
DEFAULT_KINDS: list[tuple[str, str]] = [
    ("article",  "Article publié"),
    ("kb",       "Knowledge base"),
    ("audit",    "Audit / report"),
    ("decision", "Décision éditoriale"),
    ("manual",   "Note manuelle"),
]


def _kinds() -> list[tuple[str, str]]:
    return list(getattr(settings, "RAG_MEMORY_KINDS", DEFAULT_KINDS))


def _tenant_model() -> str:
    """Returns the dotted path of the tenant model to FK against.

    Defaults to ``settings.AUTH_USER_MODEL`` so memories are scoped per user.
    Override with ``RAG_TENANT_MODEL = "sites.Site"`` (or similar) when you
    want memory scoped to a richer tenant.
    """
    return getattr(settings, "RAG_TENANT_MODEL", settings.AUTH_USER_MODEL)


def _embedding_dimensions() -> int:
    """Vector column dimension. MUST match the embedding provider's output.

    Default 512 = Voyage voyage-3.5-lite with output_dimension=512 (Matryoshka
    truncation). If you swap to OpenAI text-embedding-3-small (1536) or
    text-embedding-3-large (3072), update this and create a new migration.
    """
    return int(getattr(settings, "RAG_EMBEDDING_DIMENSIONS", 512))


class Memory(models.Model):
    """One chunk of indexed content + its pgvector embedding."""

    tenant = models.ForeignKey(
        _tenant_model(),
        on_delete=models.CASCADE,
        related_name="rag_memories",
        help_text="Owner / scope of this memory chunk.",
    )
    kind = models.CharField(
        max_length=32,
        choices=_kinds(),
        db_index=True,
        help_text="Logical type of the source (article, manual note, audit…).",
    )
    title = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text=(
            "Optional human title — often the markdown heading the chunk "
            "lives under. Improves retrieval (titles are themselves signal)."
        ),
    )
    content = models.TextField(
        help_text="The chunk body (a paragraph block, a section, etc.).",
    )
    embedding = VectorField(
        dimensions=_embedding_dimensions(),
        null=True,
        blank=True,
        help_text="pgvector cosine embedding produced by RAG_EMBEDDING_PROVIDER.",
    )
    content_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 of normalized content. Used to skip re-embedding.",
    )
    source_ref = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Pointer back to the upstream source (article slug, audit id, "
            "ticket key…). Used to purge + re-insert chunks when the source "
            "mutates."
        ),
    )
    token_count = models.PositiveIntegerField(
        default=0,
        help_text="Rough token estimate (~chars/4). Useful for prompt budgeting.",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Caller-defined attributes (author, locale, tags…).",
    )
    feedback_score = models.IntegerField(
        default=0,
        db_index=True,
        help_text=(
            "Bumped ±1 by mark_used(). Subtracted (clamped ±0.5) from cosine "
            "distance at retrieval time, so good chunks float to the top."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rag_memory"
        verbose_name = "Memory chunk"
        verbose_name_plural = "Memory chunks"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["tenant", "kind"]),
            models.Index(fields=["tenant", "source_ref"]),
        ]

    def __str__(self) -> str:
        head = self.title or (self.content[:50] if self.content else "(empty)")
        return f"[{self.kind}] {head} (tenant={self.tenant_id})"
