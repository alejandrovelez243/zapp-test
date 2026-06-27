"""Admin document lifecycle endpoints — admin-token gated.

All four endpoints require ``X-Admin-Token: <settings.admin_token>`` in the request
header.  Missing token → 401; present-but-wrong token → 403.  On any auth failure
no DB mutation is made.

Background ingest helpers open their OWN ``AsyncSession`` via ``get_sessionmaker()``
so they are fully decoupled from the request-scoped session (which is closed before
background tasks execute — see ``app.db.get_session``).

Requirements:
  faq-rag-001  POST /documents — upload + 202
  faq-rag-002  Admin-token reject (401/403, no mutation)
  faq-rag-003  Background ingest (never inline)
  faq-rag-006  GET /documents — list id/name/status
  faq-rag-007  DELETE /documents/{id} — doc + chunks removed
  faq-rag-008  PUT /documents/{id} — reingest_and_swap

Design contract: specs/faq-rag/design.md §2.7
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Security, UploadFile
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import get_settings
from app.db import get_session, get_sessionmaker
from app.rag.embeddings import EmbeddingService
from app.rag.ingest import ingest_document, reingest_and_swap
from app.rag.models import Document, DocumentChunk

router = APIRouter(prefix="/documents", tags=["documents"])

# ---------------------------------------------------------------------------
# Allowed content-type extensions
# ---------------------------------------------------------------------------

_ALLOWED: frozenset[str] = frozenset({"pdf", "md", "txt"})

# ---------------------------------------------------------------------------
# Admin-token security scheme
# ---------------------------------------------------------------------------

_admin_key_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)


async def require_admin_token(
    token: str | None = Security(_admin_key_header),
) -> None:
    """Raise 401 when the header is absent; 403 when the value is wrong.

    Reusable dependency — import and add to any route that needs admin protection.

    req: faq-rag-002
    """
    if token is None:
        raise HTTPException(status_code=401, detail="Missing admin token")
    if token != get_settings().admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DocumentCreatedResponse(BaseModel):
    """Returned by POST /documents and PUT /documents/{id}."""

    id: int


class DocumentSummary(BaseModel):
    """One row in the GET /documents response list."""

    id: int
    name: str
    status: str


# ---------------------------------------------------------------------------
# Background task helpers — each opens its OWN fresh session
# ---------------------------------------------------------------------------


async def _background_ingest(doc_id: int, content: bytes, content_type: str) -> None:
    """Run the full ingestion pipeline in a fresh session.

    Called by ``BackgroundTasks`` after the upload response is sent so the
    request-scoped session is already closed.

    req: faq-rag-003
    """
    async with get_sessionmaker()() as db:
        await ingest_document(db, doc_id, content, content_type, EmbeddingService())


async def _background_reingest(doc_id: int, content: bytes, content_type: str) -> None:
    """Re-ingest and atomically swap chunk rows in a fresh session.

    req: faq-rag-008
    """
    async with get_sessionmaker()() as db:
        await reingest_and_swap(db, doc_id, content, content_type, EmbeddingService())


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_extension(filename: str | None) -> str | None:
    """Return the lower-cased file extension when it is in ``_ALLOWED``.

    Returns ``None`` when *filename* is absent, has no dot, or the extension is
    not in the allowed set — callers must reject with 422.
    """
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext if ext in _ALLOWED else None


async def _delete_chunks(db: AsyncSession, doc_id: int) -> None:
    """Delete all ``DocumentChunk`` rows for *doc_id*.

    Called before deleting the parent ``Document`` row to satisfy the FK
    constraint without relying on CASCADE (not configured in the migration).

    req: faq-rag-007
    """
    result = await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc_id))
    for chunk in result.scalars().all():
        await db.delete(chunk)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=202, response_model=DocumentCreatedResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> DocumentCreatedResponse:
    """Accept a multipart upload → create a pending Document → schedule ingestion.

    Validates the file extension (pdf / md / txt) before any DB write.
    Returns 202 with the new document id immediately; ingestion runs in the
    background and updates ``Document.status`` to ``ready`` or ``failed``.

    req: faq-rag-001, faq-rag-003
    """
    ext = _parse_extension(file.filename)
    if ext is None:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type; allowed: pdf, md, txt",
        )
    content: bytes = await file.read()
    doc = Document(name=file.filename or "upload", content_type=ext, status="pending")
    db.add(doc)
    await db.flush()
    doc_id = doc.id
    if doc_id is None:
        raise HTTPException(status_code=500, detail="Document ID not assigned after flush")
    background_tasks.add_task(_background_ingest, doc_id, content, ext)
    return DocumentCreatedResponse(id=doc_id)


@router.get("", response_model=list[DocumentSummary])
async def list_documents(
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> list[DocumentSummary]:
    """Return id / name / status for every Document row.

    req: faq-rag-006
    """
    result = await db.execute(select(Document))
    return [
        DocumentSummary(id=d.id or 0, name=d.name, status=d.status) for d in result.scalars().all()
    ]


@router.delete("/{doc_id}", status_code=204, response_model=None)
async def delete_document(
    doc_id: int,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> None:
    """Remove the document and all its chunks; 404 when not found.

    req: faq-rag-007
    """
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await _delete_chunks(db, doc_id)
    await db.delete(doc)


@router.put("/{doc_id}", status_code=202, response_model=DocumentCreatedResponse)
async def update_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> DocumentCreatedResponse:
    """Validate the replacement file then schedule ``reingest_and_swap``.

    The existing chunk rows are preserved until the new ingest succeeds (atomic
    swap), so the corpus stays queryable throughout.

    req: faq-rag-008
    """
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    ext = _parse_extension(file.filename)
    if ext is None:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type; allowed: pdf, md, txt",
        )
    content: bytes = await file.read()
    background_tasks.add_task(_background_reingest, doc_id, content, ext)
    return DocumentCreatedResponse(id=doc_id)
