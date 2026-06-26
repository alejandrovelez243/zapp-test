"""Add history_json column to conversationsession for message-history persistence.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26

Adds a nullable ``TEXT`` column ``history_json`` to the ``conversationsession`` table.
The column stores the JSON-serialised ``list[ModelMessage]`` produced by
``ModelMessagesTypeAdapter.dump_json(result.all_messages())``.  ``NULL`` until the
first turn's messages are persisted.

Requirements: multilingual-007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add history_json column to conversationsession."""
    op.add_column(
        "conversationsession",
        sa.Column("history_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop history_json column from conversationsession."""
    op.drop_column("conversationsession", "history_json")
