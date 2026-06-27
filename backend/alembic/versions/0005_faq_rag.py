"""Add document and documentchunk tables for FAQ-RAG.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-26

Creates the ``document`` and ``documentchunk`` tables that back the FAQ-RAG
document pipeline (``app/rag/models.py``).

``document`` tracks admin-uploaded files through their ingestion lifecycle
(pending -> ingesting -> ready | failed).  ``documentchunk`` stores the
embedded text segments used for cosine-similarity retrieval.

An HNSW index with ``vector_cosine_ops`` is created on
``documentchunk.embedding`` for efficient approximate nearest-neighbour
cosine search.

The ``vector`` extension is already enabled by migration 0001
(``CREATE EXTENSION IF NOT EXISTS vector``); this migration does not repeat
that step.

All timestamp columns use ``sa.DateTime()`` (TIMESTAMP WITHOUT TIME ZONE)
matching the project-wide naive-UTC convention (asyncpg rejects tz-aware
datetimes on TIMESTAMP WITHOUT TIME ZONE columns).

Requirements: faq-rag-005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create document and documentchunk tables plus the embedding HNSW index."""
    # --- document table -------------------------------------------------------
    # Tracks admin-uploaded source files through the ingestion lifecycle.
    # req: faq-rag-005
    op.create_table(
        "document",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        # Accepted content-type category: pdf | md | txt.
        sa.Column("content_type", sa.String(), nullable=False),
        # Lifecycle state: pending | ingesting | ready | failed.
        # req: faq-rag-003, faq-rag-004, faq-rag-018
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        # Populated when status == "failed"; NULL otherwise.
        sa.Column("error", sa.String(), nullable=True),
        # Naive-UTC timestamps (TIMESTAMP WITHOUT TIME ZONE).
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- documentchunk table --------------------------------------------------
    # One row per embedded text segment; the embedding column holds the
    # pgvector representation used for cosine-similarity retrieval.
    # req: faq-rag-005
    op.create_table(
        "documentchunk",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        # FK to document.id; indexed below for fast per-document chunk lookup.
        # req: faq-rag-003, faq-rag-007
        sa.Column("document_id", sa.Integer(), nullable=False),
        # Zero-based position of this chunk within the source document.
        sa.Column("ordinal", sa.Integer(), nullable=False),
        # Raw chunk text returned to the faq_agent tool.
        sa.Column("text", sa.String(), nullable=False),
        # 1536-dimensional embedding (text-embedding-3-small).
        # Column type is pgvector's Vector — 1536 dims fixed by the model.
        # Changing dims requires a column-level migration + full re-embed.
        # req: faq-rag-005
        sa.Column("embedding", Vector(1536), nullable=False),
        # Naive-UTC creation timestamp.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
    )

    # Index on document_id for fast per-document chunk lookup.
    op.create_index(
        "ix_documentchunk_document_id",
        "documentchunk",
        ["document_id"],
        unique=False,
    )

    # HNSW index on embedding for approximate nearest-neighbour cosine search.
    # vector_cosine_ops maps to pgvector's cosine distance operator (<=>).
    # Created with raw SQL because Alembic's op.create_index does not support
    # the USING hnsw ... syntax natively.
    # req: faq-rag-005
    op.execute(
        "CREATE INDEX ix_documentchunk_embedding_hnsw "
        "ON documentchunk USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Drop documentchunk (FK dependency) then document."""
    # documentchunk has a FK to document, so it must be dropped first.
    op.drop_table("documentchunk")
    op.drop_table("document")
