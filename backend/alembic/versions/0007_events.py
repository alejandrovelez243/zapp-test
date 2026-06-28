"""Add event and enrollment tables for the events feature.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-28

Creates the ``event`` table (id, title, description, start_at, end_at, location,
timezone, created_at) and the ``enrollment`` table (id, session_id [indexed],
event_id [FK → event.id ON DELETE CASCADE, indexed], name, created_at).

Deleting an Event row cascades to its Enrollment rows via the FK constraint.
Columns use ``TIMESTAMP WITHOUT TIME ZONE`` (naive-UTC) matching ``now_utc()``
convention throughout the backend.

req: events-001 (Event table), events-004 (cascade delete),
     events-010 (Enrollment table), events-017 (name-only, no email)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create event and enrollment tables."""
    op.create_table(
        "event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        # naive-UTC — asyncpg rejects tz-aware datetimes on TIMESTAMP WITHOUT TIME ZONE
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "enrollment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # ON DELETE CASCADE: removing an Event cascades to its Enrollment rows.
        # req: events-004 — delete-event cascades enrollments
        sa.ForeignKeyConstraint(["event_id"], ["event.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Indexes declared separately for clarity.
    # req: events-010 (session_id indexed), events-004 (event_id indexed)
    op.create_index("ix_enrollment_session_id", "enrollment", ["session_id"])
    op.create_index("ix_enrollment_event_id", "enrollment", ["event_id"])


def downgrade() -> None:
    """Drop enrollment and event tables."""
    op.drop_index("ix_enrollment_event_id", table_name="enrollment")
    op.drop_index("ix_enrollment_session_id", table_name="enrollment")
    op.drop_table("enrollment")
    op.drop_table("event")
