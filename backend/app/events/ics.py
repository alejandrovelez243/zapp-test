"""RFC-5545 .ics builder for school events using the ``ics`` library.

``build_ics`` converts naive-UTC start/end datetimes to the target timezone and
produces a valid VCALENDAR string.  ``summary`` and ``description`` are passed
already in ``active_lang`` by the events agent so the .ics text is localised.

req: events-011 (tz localisation), events-012 (RFC-5545 via ics library)
Design contract: specs/events/design.md §2.2
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ics import Calendar
from ics import Event as ICSEvent


def build_ics(
    *,
    summary: str,
    description: str,
    start_at: datetime,
    end_at: datetime,
    location: str,
    tz: str,
) -> str:
    """Return an RFC-5545 VCALENDAR string for a single event.

    ``start_at`` / ``end_at`` are treated as naive-UTC (the convention throughout
    this codebase). They are converted to the IANA timezone ``tz`` before being
    passed to the ``ics`` library, which serialises them as UTC (``...Z`` suffix)
    — a fully RFC-5545-compliant representation.  The absolute UTC instants are
    preserved so any calendar app will display them in the user's local timezone.

    ``summary`` and ``description`` must already be written in the session
    ``active_lang`` — the caller (events agent ``enroll`` tool) is responsible for
    this localisation.

    Args:
        summary:     Event title / SUMMARY in active_lang.
        description: Event description in active_lang.
        start_at:    Naive-UTC start datetime (from the Event DB row).
        end_at:      Naive-UTC end datetime (from the Event DB row).
        location:    Venue / URL string.
        tz:          IANA timezone name (e.g. ``"America/Mexico_City"``). Falls
                     back to ``"UTC"`` when the name is invalid.

    Returns:
        RFC-5545 VCALENDAR string (serialised via ``Calendar.serialize()``).

    req: events-011, events-012
    """
    # Resolve the IANA timezone — fall back to UTC on any lookup error so this
    # function never raises for the caller (events-016 resilience).
    try:
        zone: ZoneInfo = ZoneInfo(tz)
    except Exception:
        zone = ZoneInfo("UTC")

    # Attach UTC tzinfo to the naive-UTC DB values, then convert to target zone.
    start_local = start_at.replace(tzinfo=UTC).astimezone(zone)
    end_local = end_at.replace(tzinfo=UTC).astimezone(zone)

    cal = Calendar()
    ev = ICSEvent()
    ev.name = summary
    ev.description = description
    ev.begin = start_local
    ev.end = end_local
    ev.location = location
    cal.events.add(ev)

    return str(cal.serialize())
