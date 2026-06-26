"""baseline: enable the pgvector ``vector`` extension

Revision ID: 0001
Revises:
Create Date: 2026-06-26

The baseline migration creates no feature tables; it only ensures the pgvector
``vector`` extension exists so later feature migrations can declare ``Vector`` columns
and HNSW indexes. ``CREATE EXTENSION IF NOT EXISTS`` is idempotent.

Requirements: platform-scaffold-006, platform-scaffold-007.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable the pgvector extension."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Drop the pgvector extension."""
    op.execute("DROP EXTENSION IF EXISTS vector")
