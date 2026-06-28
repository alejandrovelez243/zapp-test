"""Events sub-agent — lists events, confirms, enrolls (name-only) and returns a .ics.

Lazy ``get_events_agent()`` factory (mirrors ``get_faq_agent``).  The agent is invoked
by the orchestrator's ``ask_events`` tool; it keeps its own per-session message history
(``events_history_json``) and never invents event ids.

req: events-007 (list_events), events-008/-009 (confirm-then-enroll), events-010/-013
     (enroll tool: event-exists guard + persist + .ics), events-011/-015 (active_lang)
Design contract: specs/events/design.md §2.3
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from pydantic_ai import Agent, RunContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import get_settings
from app.deps import AgentDeps
from app.events.ics import build_ics
from app.events.models import Enrollment, Event

# ---------------------------------------------------------------------------
# Static instructions — NOT system_prompt; cache-eligible.
# req: events-009 (confirm), events-013 (never invent), events-015 (active_lang)
# ---------------------------------------------------------------------------
_EVENTS_INSTRUCTIONS = """
## Role
You are the Events assistant for the Zapp Global Philosophy School. You help students
discover upcoming events and enroll by providing only their name — no email needed.
You are a sub-agent; your output is a plain string returned to the orchestrator.

## Objective
Help students learn about available events and, when they want to enroll, guide them
through name-only enrollment with a confirmation step before committing.

## Capabilities & Tool Guidance
- **list_events**: ALWAYS call this to discover available events before discussing them.
  Hold the returned event ids — do not invent ids.
- **enroll(event_id, name)**: Call ONLY after the user has confirmed both the event and
  their name. The tool verifies the event exists before writing anything. If the event
  does not exist, the tool will tell you and you must relay that honestly.

## Operating Instructions
1. When the user asks about events, call ``list_events`` to get the current catalog.
2. Present the events clearly. If the user wants to enroll:
   a. Ask which event they want and their name (if not already stated).
   b. Confirm: "You'd like to enroll [name] in [event title] — is that correct?"
   c. Call ``enroll(event_id, name)`` ONLY after the user confirms.
   d. Relay the confirmation and the calendar download link from the tool result.
3. NEVER invent an event, an event_id, or a name. Use only what list_events returns.
4. Write your reply in the session active_lang (see dynamic instructions from orchestrator).

## Guardrails
- NEVER call ``enroll`` without explicit user confirmation of both the event and name.
- NEVER invent or assume an event exists — always use list_events first.
- If no events are available, say so honestly and do not fabricate events.
- If the requested event does not exist, tell the user it is unavailable.

## Tone & Style
Warm and helpful. Keep the enrollment flow simple: one question at a time, a clear
confirmation prompt, then a warm enrollment confirmation with the calendar link.
"""

# ---------------------------------------------------------------------------
# Language-localised text templates (keys: "es" | "en" | "pt").
# Used by the enroll tool to build the .ics summary/description in active_lang.
# Module-level so they are accessible in tests without calling the tool.
# req: events-011 (active_lang text), events-015
# ---------------------------------------------------------------------------
_ICS_SUMMARY_PREFIX: dict[str, str] = {
    "es": "Evento: ",
    "pt": "Evento: ",
    "en": "Event: ",
}
_ICS_LOCATION_LABEL: dict[str, str] = {
    "es": "Ubicación",
    "pt": "Local",
    "en": "Location",
}
_ENROLL_CONFIRMATION: dict[str, str] = {
    "es": "✓ {name} está inscrito/a en «{title}». Descarga tu calendario: {path}",
    "pt": "✓ {name} foi inscrito/a em «{title}». Baixe seu calendário: {path}",
    "en": "✓ {name} is enrolled in '{title}'. Download your calendar: {path}",
}


@dataclass
class _EventRow:
    """Typed view of an Event row returned by list_events.

    req: events-007 — agent holds ids so it never invents them.
    """

    id: int
    title: str
    start_at: datetime
    end_at: datetime


async def list_events(ctx: RunContext[AgentDeps]) -> list[_EventRow]:
    """Read all Event rows (id / title / start_at / end_at) from the DB.

    Returns the list so the agent holds the ids and can pass a verified id to
    ``enroll``; it never invents ids.  An empty list means no events are available.

    req: events-007
    """
    db: AsyncSession = ctx.deps.session
    result = await db.execute(select(Event))
    return [
        _EventRow(
            id=ev.id or 0,
            title=ev.title,
            start_at=ev.start_at,
            end_at=ev.end_at,
        )
        for ev in result.scalars().all()
    ]


async def enroll(ctx: RunContext[AgentDeps], event_id: int, name: str) -> str:
    """Verify the event exists, persist Enrollment, build .ics, return confirmation.

    Guards:
    - Fetches the Event row; if absent returns an error message (no write).
    - Persists ``Enrollment(session_id, event_id, name)`` only on a verified event.
    - Builds the .ics with summary/description in ``ctx.deps.active_lang`` and tz
      from ``ctx.deps.geo.timezone`` (falls back to configured default when None).

    Returns a confirmation string with the .ics download path for the orchestrator
    to relay to the user.

    req: events-008 (enroll receives resolved event_id + name),
         events-010 (persist Enrollment + .ics),
         events-011 (.ics tz from geo.timezone, text in active_lang),
         events-013 (event-exists guard — no write when absent)
    """
    db: AsyncSession = ctx.deps.session
    active_lang = ctx.deps.active_lang
    settings = get_settings()

    # Guard: verify the event exists before writing anything.
    # req: events-013 — no write on non-existent event
    event = await db.get(Event, event_id)
    if event is None:
        return f"Event {event_id} is not available. Please choose from the listed events."

    # Persist the enrollment (name-only, no email).
    # req: events-010, events-017
    enrollment = Enrollment(
        session_id=ctx.deps.session_id,
        event_id=event_id,
        name=name,
    )
    db.add(enrollment)
    await db.flush()

    # Resolve IANA timezone from geo context; fall back to configured default.
    # req: events-011 — .ics times localised to detected timezone from geo-fusion
    tz_str = ctx.deps.geo.timezone or settings.default_timezone

    # Build .ics summary/description in active_lang.  req: events-011
    prefix = _ICS_SUMMARY_PREFIX.get(active_lang, "Event: ")
    loc_label = _ICS_LOCATION_LABEL.get(active_lang, "Location")
    ics_summary = f"{prefix}{event.title}"
    ics_description = f"{event.description}\n\n{loc_label}: {event.location}"

    # Build and validate the .ics (content served via GET /events/{id}/ics endpoint).
    build_ics(
        summary=ics_summary,
        description=ics_description,
        start_at=event.start_at,
        end_at=event.end_at,
        location=event.location,
        tz=tz_str,
    )

    ics_path = f"/events/{event_id}/ics"
    tmpl = _ENROLL_CONFIRMATION.get(
        active_lang,
        "Enrolled {name} in '{title}'. Calendar: {path}",
    )
    return tmpl.format(name=name, title=event.title, path=ics_path)


@lru_cache(maxsize=1)
def get_events_agent() -> Agent[AgentDeps, str]:
    """Construct and return the cached events sub-agent (lazy factory).

    Mirrors ``get_faq_agent``: importing this module requires NO gateway key.
    The first call builds the ``Agent`` with worker_model, registers tools, and
    caches the result for the process lifetime.

    req: events-007, events-008, events-009, events-013, events-015
    Design contract: specs/events/design.md §2.3
    """
    agent: Agent[AgentDeps, str] = Agent(
        get_settings().worker_model,
        deps_type=AgentDeps,
        output_type=str,
        instructions=_EVENTS_INSTRUCTIONS,
        retries=2,
    )
    # Register tools inside the factory (lazy — key-free on import).
    # Function names become the tool names: list_events + enroll.
    # req: events-007 (list_events), events-008/-010/-013 (enroll)
    agent.tool(list_events)
    agent.tool(enroll)
    return agent
