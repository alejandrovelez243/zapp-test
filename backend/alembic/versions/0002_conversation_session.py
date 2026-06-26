"""Add conversationsession table for per-session language state.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-26

Creates the ``conversationsession`` table that backs the ``ConversationSession``
SQLModel (``app/agents/session.py``).  The table stores the resolved
``active_lang``, auto-switch counters, and housekeeping timestamps for each
chat session.

Requirements: multilingual-007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the conversationsession table."""
    op.create_table(
        "conversationsession",
        # Primary key — caller-supplied session id (no auto-increment).
        sa.Column("id", sa.String(), nullable=False),
        # Language state (all nullable; None until the first turn completes).
        sa.Column("active_lang", sa.String(), nullable=True),
        sa.Column("last_supported_lang", sa.String(), nullable=True),
        sa.Column("pending_switch_lang", sa.String(), nullable=True),
        # Auto-switch counter — starts at 0; server default avoids NULL on old rows.
        sa.Column(
            "pending_switch_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # Housekeeping timestamps — the application always supplies values (UTC).
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop the conversationsession table."""
    op.drop_table("conversationsession")
