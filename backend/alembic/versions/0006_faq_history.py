"""Add faq_history_json column to conversationsession for FAQ sub-agent memory.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-27

Adds a nullable ``TEXT`` column ``faq_history_json`` to the ``conversationsession``
table.  The column stores the JSON-serialised ``list[ModelMessage]`` for the FAQ
sub-agent's own per-session conversation history, produced by
``ModelMessagesTypeAdapter.dump_json(result.all_messages())``.  ``NULL`` until the
first FAQ turn in a session is persisted.

This column is separate from ``history_json`` (the orchestrator's own history) so
the FAQ sub-agent accumulates context independently across turns without polluting
the orchestrator's context window.

Requirements: faq-rag-019
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add faq_history_json column to conversationsession."""
    op.add_column(
        "conversationsession",
        sa.Column("faq_history_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop faq_history_json column from conversationsession."""
    op.drop_column("conversationsession", "faq_history_json")
