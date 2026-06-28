"""Admin event CRUD + student .ics download endpoints.

Admin routes (POST /events, GET /events, DELETE /events/{id},
GET /events/{id}/enrollments) require ``X-Admin-Token``; missing → 401,
wrong → 403.  The anonymous GET /events/{id}/ics endpoint is open.

The same ``require_admin_token`` dependency from ``app.api.documents`` is reused
so the auth behaviour is consistent across the admin API.

req: events-001 (create), events-002 (auth reject), events-003 (list),
     events-004 (delete + cascade), events-005 (enrollments view),
     events-010 (.ics download link)
Design contract: specs/events/design.md §2.5
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.documents import require_admin_token
from app.config import get_settings
from app.db import get_session
from app.events.ics import build_ics
from app.events.models import Enrollment, Event

router = APIRouter(prefix="/events", tags=["events"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EventCreate(BaseModel):
    """Body for POST /events.

    req: events-001
    """

    title: str
    description: str
    start_at: datetime
    end_at: datetime
    location: str
    timezone: str


class EventSummary(BaseModel):
    """One row in the GET /events response list.

    req: events-003 — id / title / start_at / end_at
    """

    id: int
    title: str
    start_at: datetime
    end_at: datetime


class EnrollmentView(BaseModel):
    """One row in the GET /events/{id}/enrollments response list.

    req: events-005 — enrolled names and timestamps
    """

    name: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=EventSummary)
async def create_event(
    body: EventCreate,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> EventSummary:
    """Create a new school event.  Returns 201 with the event summary.

    req: events-001 — admin token required; all fields persisted
    req: events-002 — token dependency rejects before any DB write
    """
    event = Event(
        title=body.title,
        description=body.description,
        start_at=body.start_at.replace(tzinfo=None),  # store naive-UTC
        end_at=body.end_at.replace(tzinfo=None),
        location=body.location,
        timezone=body.timezone,
    )
    db.add(event)
    await db.flush()
    return EventSummary(
        id=event.id or 0,
        title=event.title,
        start_at=event.start_at,
        end_at=event.end_at,
    )


@router.get("", response_model=list[EventSummary])
async def list_events(
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> list[EventSummary]:
    """Return id / title / start_at / end_at for every event row.

    req: events-003
    """
    result = await db.execute(select(Event))
    return [
        EventSummary(
            id=ev.id or 0,
            title=ev.title,
            start_at=ev.start_at,
            end_at=ev.end_at,
        )
        for ev in result.scalars().all()
    ]


@router.delete("/{event_id}", status_code=204, response_model=None)
async def delete_event(
    event_id: int,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> None:
    """Remove an event and its enrollments (ON DELETE CASCADE); 404 when not found.

    The FK ``ON DELETE CASCADE`` on ``enrollment.event_id`` removes child
    enrollment rows automatically when the parent event is deleted.

    req: events-004
    """
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    await db.delete(event)


@router.get("/{event_id}/enrollments", response_model=list[EnrollmentView])
async def list_enrollments(
    event_id: int,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _auth: None = Depends(require_admin_token),
) -> list[EnrollmentView]:
    """Return enrolled names and timestamps for one event.  404 when event not found.

    req: events-005
    """
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    result = await db.execute(select(Enrollment).where(Enrollment.event_id == event_id))
    return [EnrollmentView(name=e.name, created_at=e.created_at) for e in result.scalars().all()]


@router.get("/{event_id}/ics")
async def download_ics(
    event_id: int,
    tz: str | None = None,
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    """Return the event .ics as a downloadable calendar file (anonymous).

    The optional ``tz`` query parameter overrides the event's stored timezone
    (useful when the client knows the user's local timezone).  Falls back to the
    event's own ``timezone`` field, then to the configured ``default_timezone``.

    req: events-010 (.ics download link served via API), events-012 (RFC-5545)
    """
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    settings = get_settings()
    effective_tz = tz or event.timezone or settings.default_timezone

    ics_str = build_ics(
        summary=event.title,
        description=event.description,
        start_at=event.start_at,
        end_at=event.end_at,
        location=event.location,
        tz=effective_tz,
    )
    return Response(
        content=ics_str,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="event-{event_id}.ics"'},
    )
