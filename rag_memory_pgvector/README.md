# rag-memory-pgvector

═════════════════════════════════════════════
Template : rag-memory-pgvector
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : blog-dashboard/backend/sites_mgmt (memory_index, chunking, embeddings)
Stack    : Django 5+ / DRF / Postgres + pgvector / Voyage AI (default)
Deps     : `pgvector>=0.3`, `djangorestframework>=3.14`, `voyageai>=0.3` (optional — swappable)
Used by  : (none yet)
═════════════════════════════════════════════

Per-tenant RAG memory store. Each row is one chunk (article paragraph, KB
section, audit summary, manual note…) plus its pgvector embedding. Callers
embed a query, retrieve the top-k semantically closest chunks, inject them
into an LLM prompt, then mark which chunks helped — and those chunks float
to the top of future retrievals.

## Why this template

- **Real LLM "memory" across stateless calls.** Each Claude/GPT call sees
  only its prompt — RAG over a per-tenant memory store is how you give the
  model continuity (brand voice, prior decisions, indexed KB) without
  rebuilding the world every prompt.
- **Idempotent re-indexing.** `index_text` is safe to re-run on unchanged
  content. The `content_hash` short-circuit means editing one paragraph in a
  long article re-embeds only that paragraph — not the whole article. At
  scale that's the difference between $5 and $5,000 in embedding spend.
- **Feedback loop without a feedback DB.** `mark_used(memory_ids, rating)`
  bumps an int column. Retrieval subtracts `feedback_score * 0.01` from
  cosine distance (clamped at ±100 score → ~±0.5 cosine impact) so popular
  chunks rise without drowning out semantic match.
- **Provider-agnostic embeddings.** Defaults to Voyage AI (Anthropic-
  recommended, voyage-3.5-lite @ 512 dims via Matryoshka). Swap to OpenAI,
  Cohere, or a self-hosted model by pointing `RAG_EMBEDDING_PROVIDER` at
  your factory. Tests inject a deterministic fake provider via the same
  hook — no mocks needed.
- **Tenant model is YOUR call.** Default scopes per user
  (`settings.AUTH_USER_MODEL`); set `RAG_TENANT_MODEL = "sites.Site"` (or
  `"orgs.Workspace"`, …) to scope per a richer tenant.

## API

| Method | Path                       | Auth  | Purpose                                  |
|--------|----------------------------|-------|------------------------------------------|
| POST   | `/api/rag/index/`          | user  | Chunk + embed + upsert a source         |
| POST   | `/api/rag/retrieve/`       | user  | Embed query → top-k semantic search     |
| POST   | `/api/rag/feedback/`       | user  | Bump `feedback_score` on a batch        |

Programmatic surface (skip the views if you call from inside Python):

```python
from rag_memory_pgvector.services import (
    index_text,         # chunk + embed + upsert a markdown source
    index_chunk,        # upsert ONE pre-chunked row (no chunking)
    purge_by_source_ref,
    mark_used,
)
from rag_memory_pgvector.selectors import (
    retrieve_top_k,     # the LLM-prompt hot path
    list_for_tenant,
    count_for_tenant,
)
```

## Quickstart

```bash
pip install "pgvector>=0.3" djangorestframework
# Default provider:
pip install "voyageai>=0.3"
```

Settings:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "rag_memory_pgvector",
]

# Optional — see SETTINGS.md for the full matrix.
RAG_TENANT_MODEL = "sites.Site"          # default: settings.AUTH_USER_MODEL
RAG_EMBEDDING_DIMENSIONS = 512           # match your provider
RAG_TOP_K_DEFAULT = 8
```

URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/rag/", include("rag_memory_pgvector.urls")),
]
```

Provider key (the default Voyage provider reads this env var):

```bash
export VOYAGE_API_KEY="vk_..."
```

Migrate (this creates the `vector` extension if it doesn't exist):

```bash
python manage.py migrate rag_memory_pgvector
```

Verify:

```bash
curl -s -X POST http://127.0.0.1:8000/api/rag/index/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "manual",
    "content": "# Brand voice\n\nAlways tutoie clients. Never link to competitors.",
    "source_ref": "brand:voice"
  }'

curl -s -X POST http://127.0.0.1:8000/api/rag/retrieve/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"how do we address clients?", "k": 3}'
```

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix.

## Testing

```bash
pytest apps/rag_memory_pgvector/tests/
```

The test suite injects a deterministic fake embedding provider via the
`RAG_EMBEDDING_PROVIDER` hook — no Voyage / OpenAI API calls happen during
tests. Retrieval tests are auto-skipped when the test DB isn't Postgres
with pgvector.

## Customization hooks

- `RAG_TENANT_MODEL` — what the `Memory.tenant` FK points at (default
  `settings.AUTH_USER_MODEL`).
- `RAG_TENANT_RESOLVER` — dotted path to a callable `(request) -> tenant`
  used by the views. Default returns `request.user`.
- `RAG_MEMORY_KINDS` — list of `(value, label)` tuples for `Memory.kind`.
- `RAG_EMBEDDING_PROVIDER` — dotted path to a factory `() -> Provider`. The
  default is `rag_memory_pgvector.embeddings.make_voyage_provider`.
- `RAG_EMBEDDING_DIMENSIONS` — vector column width. Must match the provider.
- `RAG_CHUNK_SIZE_TOKENS`, `RAG_CHUNK_OVERLAP` — chunker tuning.
- `RAG_TOP_K_DEFAULT` — default `k` when callers don't pass one.

## What this does NOT include

- **Background indexing**. Indexing is synchronous in `services.index_text`.
  If your sources are big, wrap calls in a Celery task; the indexer is
  thread-safe and idempotent, so retries are free.
- **A "context formatter"**. The blog-dashboard original had a
  `format_memory_block()` that wrapped retrieved chunks in a `## MEMOIRE DU
  SITE` markdown block with instructional-kind priority. That's too
  product-specific to ship in a template — your prompt structure is yours.
  Copy it from `blog-dashboard/backend/sites_mgmt/memory_index.py` if you
  want a starting point.
- **HNSW index on the vector column**. For < 100k rows pgvector's default
  exact search is fine and avoids index-rebuild cost on every insert. Add
  ```sql
  CREATE INDEX ON rag_memory USING hnsw (embedding vector_cosine_ops);
  ```
  in a follow-up migration when you cross the threshold.
- **Reranking**. The `feedback_score` adjustment is the only re-ranking.
  Layer a cross-encoder (e.g. Voyage rerank-2) on top if you need it.
