"""Background document ingestion pipeline for FAQ-RAG.

Implements the ingestion lifecycle:
  pending -> ingesting -> ready | failed

Public functions
----------------
extract_text(content, content_type)
    Extract plain text from raw file bytes.
chunk_text(text, chunk_size, chunk_overlap)
    Split text into fixed-size character windows with overlap.
ingest_document(db, document_id, content, content_type, embedder)
    Full pipeline: extract -> chunk -> embed -> insert rows; set Document.status.
reingest_and_swap(db, document_id, content, content_type, embedder)
    Re-ingest into new chunk rows; atomically delete old rows on success.

Requirements: faq-rag-003, faq-rag-004, faq-rag-008, faq-rag-018
Design contract: specs/faq-rag/design.md §2.3
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import get_settings
from app.rag.embeddings import EmbeddingService
from app.rag.models import Document, DocumentChunk


def _now_utc() -> datetime:
    """Return the current naive-UTC datetime.

    Strips tzinfo so asyncpg accepts it on ``TIMESTAMP WITHOUT TIME ZONE`` columns.
    """
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Text extraction — req: faq-rag-003
# ---------------------------------------------------------------------------


def _extract_pdf(content: bytes) -> str:
    """Extract concatenated page text from PDF bytes using pypdf."""
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text(content: bytes, content_type: str) -> str:
    """Extract plain text from raw document bytes.

    Args:
        content: Raw file bytes (PDF, Markdown, or plain text).
        content_type: One of ``pdf`` | ``md`` | ``txt``.

    Returns:
        Extracted plain text string.

    Raises:
        ValueError: When *content_type* is not one of the accepted values.

    req: faq-rag-003
    """
    if content_type == "pdf":
        return _extract_pdf(content)
    if content_type in ("md", "txt"):
        return content.decode("utf-8")
    raise ValueError(f"Unsupported content_type: {content_type!r}")


# ---------------------------------------------------------------------------
# Chunking — req: faq-rag-003
# ---------------------------------------------------------------------------


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split *text* into fixed-size character windows with overlap.

    Args:
        text: Source text to split.
        chunk_size: Maximum characters per window (must be > 0).
        chunk_overlap: Characters shared between consecutive windows
                       (must be < *chunk_size*; ``step = chunk_size - chunk_overlap``).

    Returns:
        List of non-empty chunk strings.  Empty list when *text* is blank.

    req: faq-rag-003
    """
    if not text:
        return []
    step = max(1, chunk_size - chunk_overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        window = text[start : start + chunk_size]
        if window:
            chunks.append(window)
        start += step
    return chunks


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _set_status(
    db: AsyncSession,
    doc: Document,
    status: str,
    error: str | None = None,
) -> None:
    """Update ``doc.status`` / ``doc.error`` / ``doc.updated_at`` and flush."""
    doc.status = status
    doc.error = error
    doc.updated_at = _now_utc()
    await db.flush()


async def _insert_chunks(
    db: AsyncSession,
    document_id: int,
    chunks: list[str],
    embedder: EmbeddingService,
) -> None:
    """Embed *chunks* and bulk-insert ``DocumentChunk`` rows.

    Calls ``embedder.embed_documents`` once for the entire batch, then adds
    one ``DocumentChunk`` row per (text, vector) pair.  Flushes at the end so
    the caller can continue within the same transaction.

    req: faq-rag-003, faq-rag-004
    """
    vectors = await embedder.embed_documents(chunks)
    for ordinal, (text, embedding) in enumerate(zip(chunks, vectors, strict=True)):
        db.add(
            DocumentChunk(
                document_id=document_id,
                ordinal=ordinal,
                text=text,
                embedding=embedding,
                created_at=_now_utc(),
            )
        )
    await db.flush()


# ---------------------------------------------------------------------------
# Public ingest functions
# ---------------------------------------------------------------------------


async def ingest_document(
    db: AsyncSession,
    document_id: int,
    content: bytes,
    content_type: str,
    embedder: EmbeddingService,
) -> None:
    """Run the full ingestion pipeline for a single document.

    Lifecycle: pending -> ingesting -> (ready | failed).

    On any exception the ``Document.status`` is set to ``"failed"`` and the
    error message is stored in ``Document.error``.  All other documents remain
    queryable — the corpus stays usable.

    Args:
        db: Async DB session.
        document_id: PK of the ``Document`` row to ingest.
        content: Raw file bytes.
        content_type: ``pdf`` | ``md`` | ``txt``.
        embedder: Service used to embed the extracted text chunks.

    req: faq-rag-003, faq-rag-004, faq-rag-018
    """
    doc: Document | None = await db.get(Document, document_id)
    if doc is None:
        return  # Guard: document deleted between schedule and execution.

    settings = get_settings()
    try:
        await _set_status(db, doc, "ingesting")
        text = extract_text(content, content_type)
        chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
        if chunks:
            await _insert_chunks(db, document_id, chunks, embedder)
        await _set_status(db, doc, "ready")
        await db.commit()
    except Exception as exc:
        await _set_status(db, doc, "failed", error=str(exc))
        await db.commit()


async def reingest_and_swap(
    db: AsyncSession,
    document_id: int,
    content: bytes,
    content_type: str,
    embedder: EmbeddingService,
) -> None:
    """Re-ingest a document and atomically swap old chunk rows for new ones.

    New rows are written first (via :func:`ingest_document`).  Old rows are
    deleted **only if** the ingest succeeded (``Document.status == "ready"``).
    On failure the old chunks are preserved so retrieval degrades gracefully.

    req: faq-rag-008
    """
    old_result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )
    old_chunks: list[DocumentChunk] = list(old_result.scalars().all())

    await ingest_document(db, document_id, content, content_type, embedder)

    # Delete old rows only when the new ingest committed successfully.
    doc: Document | None = await db.get(Document, document_id)
    if doc is not None and doc.status == "ready":
        for old_chunk in old_chunks:
            await db.delete(old_chunk)
        await db.commit()
