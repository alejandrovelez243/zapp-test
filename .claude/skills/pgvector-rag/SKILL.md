---
name: pgvector-rag
description: Use when implementing the FAQ-RAG retriever, document ingestion, or document lifecycle over Postgres + pgvector
---

# pgvector RAG (FAQ retriever over uploaded docs)

Reference for the FAQ-RAG agent's storage and retrieval layer. Stack: Postgres + pgvector
(HNSW index), SQLModel tables, embeddings, top-k cosine retrieval surfaced as a PydanticAI
tool that returns **cited** chunks. RAG is **pgvector-only**; PageIndex is a documented
upgrade path (see Open Decisions), not built now.

Core invariants:
- Ingestion runs in a **BACKGROUND job**, never inline in the upload request.
- Ingested rows are **immutable**: update = re-ingest into new rows, atomic swap, delete old.
- Low/empty retrieval -> lower `confidence_score`, set `needs_review=true`, answer "I don't know".

## Data model (SQLModel)

`Document` is the lifecycle/owner row; `DocumentChunk` holds the embedded text. The vector
column uses pgvector's `Vector` type and an HNSW index for cosine search.

```python
import uuid
from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field, Column
from pgvector.sqlalchemy import Vector

EMBED_DIM = 1536  # must match the embedding model; keep in ONE config constant

class DocStatus(str, Enum):
    pending = "pending"      # uploaded, not yet ingested
    ingesting = "ingesting"
    active = "active"        # chunks queryable
    failed = "failed"        # ingestion errored; recoverable, surfaced in `list`
    superseded = "superseded"  # replaced by a re-ingest, pending GC

class Document(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str
    source_filename: str
    lang: str | None = None             # ES/EN/PT or None if mixed
    status: DocStatus = DocStatus.pending
    version: int = 1
    checksum: str                       # content hash; dedupe + change detection
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DocumentChunk(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="document.id", index=True)
    ordinal: int                        # position within doc, for citation
    content: str
    token_count: int
    embedding: list[float] = Field(sa_column=Column(Vector(EMBED_DIM)))
```

## Alembic migration (extension + HNSW index)

The extension cannot be assumed; the migration must create it. Plain Railway Postgres
**cannot** enable pgvector — provision from the pgvector template/image (see deploy notes).
HNSW is built with `vector_cosine_ops` because retrieval uses cosine distance (`<=>`).

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # ... create_table(document), create_table(documentchunk) ...
    op.execute(
        "CREATE INDEX ix_chunk_embedding_hnsw ON documentchunk "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
```

Run migrations as a Railway `preDeployCommand` (`uv run alembic upgrade head`), not at
import time. Set query-time recall with `SET hnsw.ef_search = 40;` per session if needed.

## Embedding pipeline

One embedding function, used for both ingestion and queries — the same model and
normalization on both sides, or cosine distances are meaningless. Embed in batches.

```python
async def embed_texts(texts: list[str]) -> list[list[float]]:
    # single pinned embedding model id in config; batch to respect rate limits
    resp = await embed_client.create(model=EMBED_MODEL_ID, input=texts)
    return [d.embedding for d in resp.data]
```

Chunking: split on semantic boundaries (paragraphs/headings), target ~300-500 tokens with
small overlap; store `ordinal` so a retrieved chunk can be cited back to its position.

## Document lifecycle

Upload accepts the file, writes a `Document(status=pending)`, and **enqueues** ingestion.
The HTTP handler returns immediately; ingestion happens in a background worker/task.

```python
@router.post("/admin/documents")  # admin-token protected
async def upload(file: UploadFile, bg: BackgroundTasks, ...):
    doc = await create_document(title=..., checksum=sha256(...), status="pending")
    bg.add_task(ingest_document, doc.id)   # NEVER ingest inline in the request
    return {"document_id": doc.id, "status": "pending"}
```

Ingestion job: `status=ingesting` -> chunk -> embed batches -> bulk-insert chunks ->
`status=active`. On failure leave a recoverable status and surface it in `list`.

- **list**: return documents with status + chunk counts (admin dashboard / debugging).
- **delete**: remove `Document` and cascade its chunks (FK on `document_id`).
- **update / re-ingest** (ingested rows are immutable): create a **new** `Document`
  `version = old.version + 1`, ingest its chunks, then **atomic swap** — in one
  transaction flip the new doc to `active` and the old doc to `superseded` — then delete
  the superseded rows. Readers either see the old complete version or the new complete
  version, never a half-ingested mix.

```python
async def reingest(old_id: uuid.UUID, new_content: bytes) -> uuid.UUID:
    new = await create_document(version=old.version + 1, status="pending", ...)
    await ingest_document(new.id)                      # builds new chunks
    async with session.begin():                        # atomic swap
        await set_status(new.id, "active")
        await set_status(old_id, "superseded")
    await delete_document(old_id)                       # GC old rows
    return new.id
```

## Retrieval as a PydanticAI tool (cited chunks)

Retrieval is a `@agent.tool` on the FAQ-RAG agent so the whole call is a traceable Logfire
span (`logfire.instrument_sqlalchemy(engine)` captures the SQL). It returns chunks **with
citation metadata**, and only over `active` documents. Embed the query with the *same*
`embed_texts`. Cosine **distance** is `<=>`; similarity = `1 - distance`.

```python
from dataclasses import dataclass

@dataclass
class Citation:
    document_id: uuid.UUID
    title: str
    ordinal: int
    content: str
    score: float          # cosine similarity in [0, 1]

@faq_agent.tool
async def retrieve(ctx: RunContext[AgentDeps], query: str, k: int = 5) -> list[Citation]:
    [qvec] = await embed_texts([query])
    rows = await ctx.deps.session.exec(
        select(
            DocumentChunk, Document.title,
            (1 - DocumentChunk.embedding.cosine_distance(qvec)).label("score"),
        )
        .join(Document)
        .where(Document.status == "active")
        .order_by(DocumentChunk.embedding.cosine_distance(qvec))  # ASC distance
        .limit(k)
    )
    return [Citation(c.document_id, title, c.ordinal, c.content, score)
            for c, title, score in rows]
```

The agent's instructions must require it to answer **only** from retrieved chunks and to
cite `title`/`ordinal`. Top-k cosine across all docs gives cross-doc selection for free.

## Low / empty retrieval -> degrade gracefully

Set a `MIN_SCORE` floor (config). If the best chunk is below it, or zero chunks return,
the FAQ-RAG agent must **not** hallucinate:

- Return an "I don't know" style reply in the active language (ES/EN/PT).
- Lower the turn's `confidence_score`.
- Set `needs_review=true` in the per-turn contract so it routes to review.

```python
best = max((c.score for c in chunks), default=0.0)
if not chunks or best < MIN_SCORE:
    # FAQ agent answers "I don't have that in the documents"; orchestrator/output
    # validator lowers confidence_score and sets needs_review=true on TurnOutput
    return []
```

This keeps the contract honest: missing knowledge is a measurable low-confidence signal,
not a confident wrong answer.

## Open Decisions / Rejected Alternatives

- **PageIndex (deferred upgrade path)**: a reasoning/tree retrieval layer that can replace
  flat top-k cosine for large or hierarchical corpora. Documented as the upgrade path; the
  schema (immutable versioned chunks) is compatible. **Not built now** — pgvector-only.
- **Hybrid search (ready, not enabled)**: schema supports adding lexical/BM25 (e.g. a
  `tsvector` column) to fuse with vector scores. Keep the door open; ship cosine first.
- **HNSW vs IVFFlat**: HNSW chosen for recall/latency at this corpus size; IVFFlat is the
  fallback if build memory becomes a constraint.
