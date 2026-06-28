"""Add events_history_json column to conversationsession for events sub-agent memory.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-28

Adds a nullable ``TEXT`` column ``events_history_json`` to the ``conversationsession``
table.  The column stores the JSON-serialised ``list[ModelMessage]`` for the events
sub-agent's own per-session conversation history, produced by
``ModelMessagesTypeAdapter.dump_json(result.all_messages())``.  ``NULL`` until the
first events turn in a session is persisted.

This column is separate from ``history_json`` (orchestrator history) and
``faq_history_json`` (FAQ sub-agent history) so the events sub-agent accumulates
enrollment context independently across turns without polluting the other contexts.

req: events-014
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add events_history_json column to conversationsession."""
    op.add_column(
        "conversationsession",
        sa.Column("events_history_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop events_history_json column from conversationsession."""
    op.drop_column("conversationsession", "events_history_json")
