# SETTINGS — rag-memory-pgvector

## pip dependencies

```
pgvector>=0.3
djangorestframework>=3.14
voyageai>=0.3          # default provider — drop if you swap to OpenAI/Cohere
```

Optional:

```
openai>=1.0            # if RAG_EMBEDDING_PROVIDER points at an OpenAI factory
django-unfold          # admin polish; falls back to stock ModelAdmin
```

## Database

Requires PostgreSQL with the `vector` extension. The initial migration runs

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

so a fresh DB just works. On managed Postgres:

- **Supabase**: extension available out of the box.
- **AWS RDS**: add `vector` to the `rds.extensions` parameter group, restart.
- **Railway**: works on the default Postgres image.
- **SQLite**: not supported — pgvector is a Postgres extension.

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "rag_memory_pgvector",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/rag/", include("rag_memory_pgvector.urls")),
]
```

## Configurable settings (all optional)

```python
# settings.py — every setting has a sensible default.

# --- Tenant model ---------------------------------------------------------
# What the Memory.tenant FK points at. Default = your auth user. Set to a
# richer tenant ("sites.Site", "orgs.Workspace") when memory is shared
# across users of one tenant.
RAG_TENANT_MODEL = "sites.Site"   # default: settings.AUTH_USER_MODEL

# Dotted path to a callable (request) -> tenant_instance used by the API
# views. Default resolver returns request.user; override when your tenant
# model isn't the user (e.g. parse ?site=<id> from the request).
RAG_TENANT_RESOLVER = "myproj.rag.get_tenant_from_request"

# --- Memory kinds ---------------------------------------------------------
# Choices for Memory.kind. The column is CharField(max_length=32) so adding
# kinds requires no migration. Defaults shown:
RAG_MEMORY_KINDS = [
    ("article",  "Article publié"),
    ("kb",       "Knowledge base"),
    ("audit",    "Audit / report"),
    ("decision", "Décision éditoriale"),
    ("manual",   "Note manuelle"),
]

# --- Embedding provider ---------------------------------------------------
# Dotted path to a factory `() -> Provider`. A Provider is any object with
# embed_text(text, input_type="document") -> list[float] and
# embed_batch(texts, input_type="document") -> list[list[float]].
#
# Default: rag_memory_pgvector.embeddings.make_voyage_provider
# (voyage-3.5-lite @ 512 dims, requires VOYAGE_API_KEY env var).
RAG_EMBEDDING_PROVIDER = "myproj.rag.make_openai_provider"

# Vector column dimension. MUST match what the provider returns. Default 512
# (Voyage voyage-3.5-lite with Matryoshka truncation). Change values:
#   - voyage-3.5         @ default     : 1024
#   - voyage-3.5-lite    @ 512         : 512 (default)
#   - OpenAI text-embedding-3-small    : 1536
#   - OpenAI text-embedding-3-large    : 3072
# Changing this after migration requires a new migration that alters the
# embedding column dimension AND a full re-index (old embeddings are stale).
RAG_EMBEDDING_DIMENSIONS = 1536

# --- Chunking -------------------------------------------------------------
# Target chunk size in TOKENS (~chars/4). Bigger = fewer chunks per source
# but each chunk eats more prompt budget at retrieval.
RAG_CHUNK_SIZE_TOKENS = 250   # default 250 ≈ 1000 chars

# Overlap between adjacent chunks (in tokens), so long sections preserve
# context across splits.
RAG_CHUNK_OVERLAP = 25        # default 25 ≈ 100 chars

# --- Retrieval ------------------------------------------------------------
# Default `k` when callers don't pass one.
RAG_TOP_K_DEFAULT = 8
```

## Env vars

```
VOYAGE_API_KEY=vk_xxx         # required by the DEFAULT provider only
```

If you swap `RAG_EMBEDDING_PROVIDER` to OpenAI, set `OPENAI_API_KEY` instead
(your factory reads it).

## Post-install verification

```bash
python manage.py check
python manage.py migrate rag_memory_pgvector
pytest apps/rag_memory_pgvector/tests/

# curl smoke (replace $TOKEN with a valid auth token):
curl -s -X POST http://127.0.0.1:8000/api/rag/index/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"manual","content":"# Voice\n\nAlways tutoie clients.","source_ref":"brand:voice"}'

curl -s -X POST http://127.0.0.1:8000/api/rag/retrieve/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"how do we address clients?", "k": 3}'

curl -s -X POST http://127.0.0.1:8000/api/rag/feedback/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"memory_ids":[1,2,3], "rating": 1}'
```

## Scaling tips

- **HNSW index** when row count crosses ~100k:
  ```sql
  CREATE INDEX rag_memory_embedding_hnsw
    ON rag_memory USING hnsw (embedding vector_cosine_ops);
  ```
  Add it in a follow-up migration with `migrations.RunSQL`.
- **Background indexing**: wrap `index_text` in a Celery task once sources
  exceed a few KB. Idempotent + delta-aware, so retries are free.
- **Cost**: with Voyage voyage-3.5-lite @ $0.02/1M tokens, a 10k-chunk site
  ≈ 2.5M tokens ≈ $0.05 to index from scratch. Hash-skip on edits keeps
  ongoing cost negligible.
