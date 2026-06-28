"""SQLModel tables for the events feature: Event + Enrollment (name-only, no email).

Event rows are admin-managed (CRUD via /events endpoints). Enrollment rows are
written by the events agent enroll tool after user confirmation; they are keyed by
session_id + event_id + name and cascade-deleted when the parent Event is removed.

req: events-001 (Event admin create), events-004 (cascade delete),
     events-010 (Enrollment persist), events-017 (name-only, no email)
Design contract: specs/events/design.md §2.1, §4
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.time import now_utc


class Event(SQLModel, table=True):
    """One row per school event.

    ``start_at`` / ``end_at`` are naive-UTC (asyncpg rejects tz-aware on TIMESTAMP).
    ``timezone`` is the IANA timezone name used to localise the .ics output.

    req: events-001, events-003
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    description: str
    # naive-UTC — asyncpg rejects tz-aware datetimes on TIMESTAMP WITHOUT TIME ZONE.
    start_at: datetime
    end_at: datetime
    location: str
    # IANA timezone name (e.g. "America/Mexico_City") — used by build_ics for DTSTART TZID.
    timezone: str
    created_at: datetime = Field(default_factory=now_utc)


class Enrollment(SQLModel, table=True):
    """One row per student enrollment in an event.

    ``session_id`` identifies the chat session; ``event_id`` is an FK to
    ``Event.id`` with ON DELETE CASCADE so removing an event also removes its
    enrollments.  Only the student's name is persisted — no email.

    req: events-010 (persist), events-017 (name-only, no email)
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    # FK to event.id; ON DELETE CASCADE is declared in the Alembic migration (0007).
    event_id: int = Field(index=True, foreign_key="event.id")
    name: str  # no email — req: events-017
    created_at: datetime = Field(default_factory=now_utc)
