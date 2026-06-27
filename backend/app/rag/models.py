"""SQLModel table definitions for the FAQ-RAG document pipeline.

``Document`` tracks admin-uploaded files through their ingestion lifecycle
(pending -> ingesting -> ready | failed).  ``DocumentChunk`` stores the
embedded text segments used for cosine-similarity retrieval via pgvector.

The HNSW index on ``DocumentChunk.embedding`` (``vector_cosine_ops``) is
created in Alembic migration 0005.

Requirements: faq-rag-005
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlmodel import Column, Field, SQLModel

from app.time import now_utc


class Document(SQLModel, table=True):
    """Admin-uploaded source document.

    Rows are created at upload time (``status="pending"``) and updated by the
    background ingestion job as it moves through the pipeline.

    req: faq-rag-005
    """

    # Surrogate auto-increment primary key.
    id: int | None = Field(default=None, primary_key=True)

    # Human-readable name (e.g. original filename).
    name: str

    # Accepted MIME/extension category: ``pdf`` | ``md`` | ``txt``.
    content_type: str

    # Ingestion lifecycle state.
    # req: faq-rag-003, faq-rag-004, faq-rag-018
    status: str = "pending"

    # Error message when ``status == "failed"``; None otherwise.
    error: str | None = None

    # Naive-UTC creation and last-update timestamps.
    # req: faq-rag-005
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class DocumentChunk(SQLModel, table=True):
    """Embedded text segment produced during document ingestion.

    One row per chunk; ``embedding`` holds the 1536-dimensional pgvector
    representation used for cosine-similarity retrieval.

    req: faq-rag-005
    """

    # Surrogate auto-increment primary key.
    id: int | None = Field(default=None, primary_key=True)

    # Parent document reference; indexed for fast per-document chunk lookup.
    # req: faq-rag-003, faq-rag-007
    document_id: int = Field(index=True, foreign_key="document.id")

    # Zero-based position of this chunk within the source document.
    ordinal: int

    # Raw chunk text returned to the faq_agent tool.
    text: str

    # 1536-dimensional embedding (text-embedding-3-small @ 1536 dims).
    # ``sa_column`` bypasses SQLModel generic inference and uses pgvector's
    # Vector type directly; 1536 dims is fixed by the model (changing requires
    # a column-level migration + full re-embed of all chunk rows).
    # req: faq-rag-005
    embedding: list[float] = Field(sa_column=Column(Vector(1536)))

    # Naive-UTC creation timestamp; asyncpg rejects tz-aware datetimes.
    created_at: datetime = Field(default_factory=now_utc)
