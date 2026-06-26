---
name: fastapi-sqlmodel
description: Use when writing FastAPI endpoints, SQLModel models, async DB access, Alembic migrations, or the request->agent boundary
---

# FastAPI + SQLModel + the request->agent boundary

Reference for the backend HTTP layer that sits between Next.js and the PydanticAI
orchestrator. Everything is async. The chat endpoint NEVER returns a 500 for a
model/network error — it degrades to a valid `needs_review=true` TurnOutput.

## Async engine + AsyncSession

One async engine per process; one session per request via a generator dependency.

```python
# app/db.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)  # postgresql+asyncpg://
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session            # commit explicitly in the endpoint/service; rollback on error
```

`expire_on_commit=False` so returned ORM objects stay usable after commit when
serializing the response. Use `asyncpg`, never the sync `psycopg2` driver.

## SQLModel conventions (table vs schema models)

SQLModel = SQLAlchemy table + Pydantic model. Keep **table models** (DB rows) and
**schema models** (API I/O) as separate classes. Lean on Pydantic heavily for
validation; do not hand-roll dict shaping. Treat ingested chunks as immutable.

```python
# app/models.py
from sqlmodel import SQLModel, Field
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from enum import Enum
import uuid, datetime as dt

class DocStatus(str, Enum):                    # document lifecycle
    pending = "pending"
    ingesting = "ingesting"
    active = "active"
    failed = "failed"
    superseded = "superseded"

class DocumentBase(SQLModel):                 # shared fields
    filename: str
    lang: str = "en"

class Document(DocumentBase, table=True):     # TABLE model (a row)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: DocStatus = DocStatus.pending      # pending|ingesting|active|failed|superseded
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))

class DocumentChunk(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="document.id", index=True)
    content: str
    embedding: list[float] = Field(sa_column=Column(Vector(1536)))  # HNSW index in migration

class DocumentRead(DocumentBase):              # SCHEMA model (response) — never expose raw rows
    id: uuid.UUID
    status: DocStatus
```

Conventions: UUID PKs; tz-aware UTC timestamps; `index=True` on FKs and filter
columns; one module of table models, one of request/response schemas. Never
return a `table=True` instance directly — map to a `*Read` schema.

## Request-scoped dependency that builds AgentDeps

The boundary's most important job: assemble the PydanticAI `AgentDeps` for THIS
request (DB session + retriever + geo/lang clients + session state) and inject it.
Build per request so the `AsyncSession` and per-IP geo context are correctly scoped.

```python
# app/deps.py
@dataclass
class AgentDeps:                       # carried via RunContext[AgentDeps] inside the agent
    session: AsyncSession
    retriever: PgVectorRetriever       # top-k cosine over DocumentChunk
    geo_client: httpx.AsyncClient      # ipinfo.io / ipapi.co + REST Countries (instrumented)
    lang_detector: LinguaDetector      # deterministic detector fused with the LLM's guess
    session_id: str
    request_ip: str
    active_lang: str | None            # locked language from prior turns, replayed from history

async def build_agent_deps(
    request: Request,
    session: AsyncSession = Depends(get_session),
    session_id: str = Header(...),
) -> AgentDeps:
    state = await load_session_state(session, session_id)   # active_lang, message history
    return AgentDeps(
        session=session,
        retriever=PgVectorRetriever(session),
        geo_client=request.app.state.http,                  # shared pooled client
        lang_detector=request.app.state.lingua,
        session_id=session_id,
        request_ip=request.headers.get("x-forwarded-for", request.client.host).split(",")[0],
        active_lang=state.active_lang,
    )
```

The geo/lang fusion itself happens INSIDE a PydanticAI tool (a Logfire span) and is
reconciled in an `output_validator` — see the pydantic-ai-conventions skill. The
boundary only wires the clients in.

## The error boundary (never a 500 for model errors)

Catch PydanticAI failures and degrade to a schema-valid TurnOutput with
`needs_review=true`. A model/network fault is a product state, not an HTTP error.

```python
# app/routers/chat.py
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

@router.post("/chat", response_model=TurnOutput)
async def chat(body: ChatIn, deps: AgentDeps = Depends(build_agent_deps)):
    try:
        result = await orchestrator.run(
            body.message, deps=deps, message_history=deps.history,
            usage_limits=UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=20000),
        )
        await persist_turn(deps.session, deps.session_id, result.all_messages())
        await deps.session.commit()
        return result.output                       # already a validated TurnOutput
    except (ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded) as exc:
        await deps.session.rollback()
        logfire.warning("agent_degraded", error=str(exc))
        return degraded_turn(deps.active_lang or settings.FALLBACK_LANG, reason=str(exc))
```

`degraded_turn(...)` returns the canonical contract with safe defaults:

```python
def degraded_turn(active_lang: str, reason: str) -> TurnOutput:
    return TurnOutput(
        reply=apology_in(active_lang),
        detected_lang=active_lang, active_lang=active_lang, lang_confidence=0.0,
        final_normalized_text="", detected_country=None, confidence_score=0.0,
        needs_review=True, guardrails={"input": [], "output": []},
    )
```

The contract every successful turn also emits, verbatim:

```json
{
  "reply": "string",                  // user-facing answer
  "detected_lang": "es",              // ISO 639-1 the user wrote in
  "active_lang": "es",                // language the session is locked to
  "lang_confidence": 0.97,            // agreement score LLM vs detector
  "final_normalized_text": "string",  // LLM + API fused, locale-normalized
  "detected_country": "MX",           // fused geo signal (ISO 3166-1 alpha-2)
  "confidence_score": 0.0,            // combined logic
  "needs_review": false,              // true on low confidence / divergence / errors
  "guardrails": { "input": [], "output": [] }  // triggered guardrail names
}
```

Supported languages: ES, EN, PT. Unsupported language -> set `active_lang` to the
configured fallback AND `needs_review=true`, degrade gracefully. Reserve real HTTP
errors (400/401/422) for malformed requests, bad admin token, and validation — not
for model faults.

## Streaming chat endpoint

Stream tokens for UX, but the FINAL frame is still the full validated TurnOutput so
the client always receives the contract. Output validators run on partials too.

```python
@router.post("/chat/stream")
async def chat_stream(body: ChatIn, deps: AgentDeps = Depends(build_agent_deps)):
    async def gen():
        try:
            async with orchestrator.run_stream(body.message, deps=deps,
                                                message_history=deps.history) as stream:
                async for text in stream.stream_text(delta=True):
                    yield sse("token", text)
                out = await stream.get_output()        # validated TurnOutput
                await persist_turn(deps.session, deps.session_id, stream.all_messages())
                await deps.session.commit()
                yield sse("final", out.model_dump_json())
        except (ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded) as exc:
            await deps.session.rollback()
            yield sse("final", degraded_turn(deps.active_lang or settings.FALLBACK_LANG,
                                             str(exc)).model_dump_json())
    return StreamingResponse(gen(), media_type="text/event-stream")
```

## Admin-token dependency for management routes

Doc/event management is admin-token gated; chat is anonymous with a `session_id`.

```python
async def require_admin(x_admin_token: str = Header(...)) -> None:
    if not secrets.compare_digest(x_admin_token, settings.ADMIN_TOKEN):
        raise HTTPException(401, "invalid admin token")

admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
```

Use `secrets.compare_digest` (constant-time). Apply at the router level so every
upload/list/delete route inherits it.

## Background ingestion (never inline)

Upload returns immediately; chunk + embed in a BackgroundTask. Re-ingest = write new
rows, atomic swap, delete old (chunks are immutable).

```python
@admin.post("/documents", response_model=DocumentRead, status_code=202)
async def upload(file: UploadFile, bg: BackgroundTasks,
                 session: AsyncSession = Depends(get_session)):
    doc = Document(filename=file.filename, status=DocStatus.pending)
    session.add(doc); await session.commit(); await session.refresh(doc)
    bg.add_task(ingest_document, doc.id, await file.read())   # own session inside the task
    return DocumentRead.model_validate(doc)
```

`ingest_document` opens its OWN `SessionLocal()` (the request session is closed by
the time it runs), sets `status` ingesting->active/failed, and writes chunks +
embeddings. For multi-worker reliability prefer a real queue; a BackgroundTask is the
documented baseline. Low/empty retrieval at query time -> lower `confidence_score` +
`needs_review=true`.

## Alembic (pgvector extension first)

Plain Railway Postgres cannot enable pgvector — use the pgvector image. The FIRST
migration must create the extension before any `Vector` column or HNSW index.

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("document", ...)
    op.create_table("documentchunk", ...)   # embedding = Vector(1536)
    op.execute(
        "CREATE INDEX ix_chunk_embedding ON documentchunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )
```

Run migrations as Railway `preDeployCommand`: `uv run alembic upgrade head`. Import
SQLModel metadata into `env.py` for autogenerate, but hand-write the extension +
HNSW lines — autogenerate will not emit them.
