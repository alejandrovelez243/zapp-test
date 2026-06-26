"""Add sessiongrade table and graded_at column on conversationsession.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-26

Creates the ``sessiongrade`` table that backs the ``SessionGrade`` SQLModel
(``app/agents/session.py``) and adds the ``graded_at`` nullable column to the
existing ``conversationsession`` table.

- ``sessiongrade`` stores per-conversation evaluation scores (1-5) produced by
  the runtime judge (``app/eval/runtime.py::evaluate_conversation``).
- ``graded_at`` is the sweep guard on ``conversationsession``; the idle-sweep
  skips rows where this column is not NULL.

All timestamp columns use ``sa.DateTime()`` (TIMESTAMP WITHOUT TIME ZONE) to
match the project-wide naive-UTC convention (asyncpg rejects tz-aware datetimes
on these columns).

Requirements: evaluation-016
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create sessiongrade table and add graded_at to conversationsession."""
    # --- sessiongrade table ---------------------------------------------------
    # Backs SessionGrade (app/agents/session.py).  All timestamps are naive-UTC
    # (TIMESTAMP WITHOUT TIME ZONE); asyncpg rejects tz-aware datetimes here.
    op.create_table(
        "sessiongrade",
        # Surrogate auto-increment primary key.
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        # Session reference (by convention; no FK constraint to keep migrations
        # decoupled from table ordering).  Indexed for fast lookup by session.
        sa.Column("session_id", sa.String(), nullable=False),
        # Discrete judge score 1-5.
        sa.Column("score", sa.Integer(), nullable=False),
        # Optional judge rationale; empty string when unavailable.
        sa.Column(
            "rationale",
            sa.String(),
            nullable=False,
            server_default="",
        ),
        # Flags sessions scoring below judge_mean threshold for human review.
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        # Audit trail: the judge model id that produced this grade.
        sa.Column("model", sa.String(), nullable=False),
        # Row creation timestamp — naive-UTC; application always supplies value.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Index on session_id for fast lookup (mirrors Field(index=True) on the model).
    op.create_index(
        "ix_sessiongrade_session_id",
        "sessiongrade",
        ["session_id"],
        unique=False,
    )

    # --- graded_at on conversationsession ------------------------------------
    # Sweep guard: NULL = not yet graded; non-NULL = grade already persisted.
    # req: evaluation-016, evaluation-018
    op.add_column(
        "conversationsession",
        sa.Column("graded_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Drop graded_at from conversationsession and drop sessiongrade table."""
    # Reverse order: column first, then the table.
    op.drop_column("conversationsession", "graded_at")
    op.drop_index("ix_sessiongrade_session_id", table_name="sessiongrade")
    op.drop_table("sessiongrade")
