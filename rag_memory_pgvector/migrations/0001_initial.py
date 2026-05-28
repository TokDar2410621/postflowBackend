"""Initial migration for rag_memory_pgvector.

Enables the pgvector PostgreSQL extension BEFORE creating the table that
uses ``VectorField`` — otherwise the CREATE TABLE fails on a fresh DB.

If you're using a managed Postgres (Supabase, RDS, Railway) you'll need
the ``vector`` extension whitelisted. On Supabase it's available out of
the box. On RDS you may need to add ``vector`` to your parameter group's
``rds.extensions`` allowlist first.

If you're not on Postgres at all, this migration will fail loudly — the
template only supports Postgres because pgvector is a Postgres extension.
"""
from django.conf import settings
from django.db import migrations, models

import pgvector.django


def _embedding_dims():
    return int(getattr(settings, "RAG_EMBEDDING_DIMENSIONS", 512))


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(
            getattr(settings, "RAG_TENANT_MODEL", settings.AUTH_USER_MODEL),
        ),
    ]

    operations = [
        # Enable pgvector. Idempotent — safe to re-run.
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name="Memory",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name="ID",
                )),
                ("kind", models.CharField(db_index=True, max_length=32)),
                ("title", models.CharField(blank=True, default="", max_length=300)),
                ("content", models.TextField()),
                ("embedding", pgvector.django.VectorField(
                    blank=True, dimensions=_embedding_dims(), null=True,
                )),
                ("content_hash", models.CharField(db_index=True, max_length=64)),
                ("source_ref", models.CharField(
                    blank=True, db_index=True, default="", max_length=200,
                )),
                ("token_count", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("feedback_score", models.IntegerField(db_index=True, default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    related_name="rag_memories",
                    to=getattr(
                        settings, "RAG_TENANT_MODEL", settings.AUTH_USER_MODEL,
                    ),
                )),
            ],
            options={
                "verbose_name": "Memory chunk",
                "verbose_name_plural": "Memory chunks",
                "db_table": "rag_memory",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="memory",
            index=models.Index(
                fields=["tenant", "kind"],
                name="rag_memory_tenant_kind_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="memory",
            index=models.Index(
                fields=["tenant", "source_ref"],
                name="rag_memory_tenant_src_idx",
            ),
        ),
    ]
