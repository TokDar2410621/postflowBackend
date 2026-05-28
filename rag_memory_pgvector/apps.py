from django.apps import AppConfig


class RagMemoryPgvectorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rag_memory_pgvector"
    label = "rag_memory_pgvector"
    verbose_name = "RAG Site Memory (pgvector)"
