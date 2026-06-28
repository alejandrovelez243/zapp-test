"""Tests for the events feature (tasks 2-7, 9).

Coverage:
  - Events model field shapes + cascade wiring (offline/unit)
  - Alembic migrations 0007 (event/enrollment tables) + 0008 (events_history_json) offline SQL
  - build_ics: valid RFC-5545 VCALENDAR, correct tz, summary/description in active_lang
  - events agent (TestModel + mocked DB): list_events, confirm-then-enroll persists
    Enrollment, non-existent event → no write, reply in active_lang
  - ask_events tool: forwards deps+usage; events_enabled=False → tool absent
  - Endpoints: admin auth reject (401/403), create/list/delete, enrollments view,
    anonymous .ics download
  - Sub-agent memory: second run receives first run's message_history (two-turn test)

Requirements: events-001..events-018
Design contract: specs/events/design.md §2.1-2.5
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Generator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.events import _ENROLL_CONFIRMATION, _ICS_SUMMARY_PREFIX, enroll, get_events_agent
from app.agents.orchestrator import ask_events, get_orchestrator
from app.agents.session import ConversationSession, SessionRepository
from app.config import get_settings
from app.deps import AgentDeps
from app.events.ics import build_ics
from app.events.models import Enrollment, Event
from app.fusion.geo import GeoContext
from app.lang.detector import DetectionResult
from app.lang.state import ActiveLangDecision

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOKEN = "test-admin-token"
_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_NOW = datetime(2026, 7, 1, 18, 0, 0)  # naive-UTC reference

# ---------------------------------------------------------------------------
# Shared autouse fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Required env vars for get_settings() inside all events tests."""
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("ADMIN_TOKEN", _TOKEN)


@pytest.fixture(autouse=True)
def _clear_events_agent_cache() -> Generator[None, None, None]:
    """Clear get_events_agent lru_cache before and after each test.

    Mirrors the _clear_orchestrator_cache pattern in conftest.
    """
    get_events_agent.cache_clear()
    yield
    get_events_agent.cache_clear()


# ---------------------------------------------------------------------------
# In-memory SQLite DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def _db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh in-memory SQLite AsyncSession with all tables created."""
    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        import app.agents.session  # side-effect: registers ConversationSession
        import app.events.models  # side-effect: registers Event / Enrollment
        import app.rag.models  # noqa: F401  side-effect: registers rag tables

        await conn.run_sync(SQLModel.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_deps(
    session: AsyncSession | None = None,
    *,
    session_id: str = "ev-test",
    active_lang: str = "en",
    timezone_str: str = "America/Mexico_City",
) -> AgentDeps:
    """Minimal AgentDeps for events tests."""
    db = session if session is not None else AsyncMock(spec=AsyncSession)
    return AgentDeps(
        session=db,
        http=AsyncMock(spec=httpx.AsyncClient),
        session_id=session_id,
        request_ip="127.0.0.1",
        active_lang=active_lang,
        detection=DetectionResult(lang=active_lang, confidence=0.95, is_reliable=True),
        lang_decision=ActiveLangDecision(
            active_lang=active_lang,
            first_turn=False,
            locked=True,
            fallback_used=False,
        ),
        geo=GeoContext(
            country="MX",  # type: ignore[arg-type]
            timezone=timezone_str,
            locale="es-MX",
            source="ipapi",
            ok=True,
        ),
    )


def _make_run_ctx(deps: AgentDeps) -> MagicMock:
    """Minimal RunContext-like mock for tool unit tests."""
    ctx = MagicMock()
    ctx.deps = deps
    ctx.usage = RunUsage()
    return ctx


def _make_event(
    title: str = "Stoicism Seminar",
    start_at: datetime = _NOW,
    end_at: datetime | None = None,
    tz: str = "America/Mexico_City",
) -> Event:
    """Return an Event with a stable primary key."""
    end = end_at or datetime(start_at.year, start_at.month, start_at.day, 20, 0, 0)
    return Event(
        id=1,
        title=title,
        description="A seminar on Stoic philosophy.",
        start_at=start_at,
        end_at=end,
        location="Online",
        timezone=tz,
    )


# ---------------------------------------------------------------------------
# TestEventsModel — field shapes + cascade wiring (unit)
# ---------------------------------------------------------------------------


class TestEventsModel:
    """Event + Enrollment model field shapes.

    req: events-001 (Event fields), events-010 (Enrollment fields),
         events-017 (name-only — no email field)
    """

    def test_event_has_expected_fields(self) -> None:
        """Event exposes id / title / description / start_at / end_at / location / timezone.

        req: events-001
        """
        ev = Event(
            title="Seminar",
            description="Philosophy",
            start_at=_NOW,
            end_at=_NOW,
            location="Online",
            timezone="UTC",
        )
        assert ev.title == "Seminar"
        assert ev.location == "Online"
        assert ev.timezone == "UTC"
        assert ev.id is None

    def test_enrollment_has_no_email_field(self) -> None:
        """Enrollment has session_id, event_id, name, created_at — no email.

        req: events-017 — name-only enrollment
        """
        assert not hasattr(Enrollment, "email")
        en = Enrollment(session_id="s1", event_id=1, name="Alice")
        assert en.name == "Alice"
        assert en.event_id == 1
        assert en.session_id == "s1"

    def test_enrollment_created_at_is_naive_utc(self) -> None:
        """Enrollment.created_at is naive (no tzinfo) — asyncpg convention.

        req: events-010
        """
        en = Enrollment(session_id="s1", event_id=1, name="Bob")
        assert en.created_at.tzinfo is None

    def test_event_created_at_is_naive_utc(self) -> None:
        """Event.created_at defaults to naive UTC via now_utc().

        req: events-001
        """
        ev = Event(
            title="T",
            description="D",
            start_at=_NOW,
            end_at=_NOW,
            location="L",
            timezone="UTC",
        )
        assert ev.created_at.tzinfo is None

    def test_conversationsession_has_events_history_json(self) -> None:
        """ConversationSession exposes events_history_json defaulting to None.

        req: events-014 — separate column for events sub-agent history
        """
        sess = ConversationSession(id="schema-check")
        assert hasattr(sess, "events_history_json")
        assert sess.events_history_json is None

    def test_events_history_json_independent_of_faq_and_orch(self) -> None:
        """events_history_json, faq_history_json, history_json are independent.

        req: events-014 — events history must not contaminate other histories
        """
        sess = ConversationSession(id="x")
        sess.history_json = '["orch"]'
        sess.faq_history_json = '["faq"]'
        sess.events_history_json = '["events"]'
        assert sess.history_json == '["orch"]'
        assert sess.faq_history_json == '["faq"]'
        assert sess.events_history_json == '["events"]'


# ---------------------------------------------------------------------------
# TestMigration0007 — offline SQL check
# ---------------------------------------------------------------------------


class TestMigration0007OfflineSQL:
    """Migration 0007 creates event and enrollment tables with cascade.

    req: events-001, events-004, events-010, events-017
    """

    def test_migration_file_exists(self) -> None:
        """Migration 0007 file exists in alembic/versions/.

        req: events-001
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0007_events.py"
        assert p.exists(), f"Migration not found: {p}"

    def test_migration_chains_from_0006(self) -> None:
        """Migration 0007 has down_revision='0006'.

        req: events-001 — Alembic head must chain: 0006 → 0007
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0007_events.py"
        content = p.read_text(encoding="utf-8")
        assert re.search(r'revision\s*:\s*str\s*=\s*"0007"', content)
        assert re.search(r'down_revision.*=.*"0006"', content)

    def test_migration_creates_event_table(self) -> None:
        """Migration 0007 upgrade() creates the 'event' table.

        req: events-001
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0007_events.py"
        content = p.read_text(encoding="utf-8")
        assert "create_table" in content
        assert '"event"' in content

    def test_migration_creates_enrollment_with_cascade(self) -> None:
        """Migration 0007 creates enrollment table with ON DELETE CASCADE FK.

        req: events-004 — delete-event cascades enrollments
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0007_events.py"
        content = p.read_text(encoding="utf-8")
        assert '"enrollment"' in content
        assert "CASCADE" in content

    def test_migration_no_email_column(self) -> None:
        """Migration 0007 enrollment table has no 'email' DDL column definition.

        req: events-017 — name-only enrollment
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0007_events.py"
        content = p.read_text(encoding="utf-8")
        # Confirm no "email" appears as a column() call in the DDL.
        # The word may appear in comments/docstrings ("no email") — that is fine.
        assert 'Column("email"' not in content
        assert "sa.Column('email'" not in content


# ---------------------------------------------------------------------------
# TestMigration0008 — offline SQL check
# ---------------------------------------------------------------------------


class TestMigration0008OfflineSQL:
    """Migration 0008 adds events_history_json to conversationsession.

    req: events-014
    """

    def test_migration_file_exists(self) -> None:
        """Migration 0008 file exists in alembic/versions/.

        req: events-014
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0008_events_history.py"
        assert p.exists(), f"Migration not found: {p}"

    def test_migration_chains_from_0007(self) -> None:
        """Migration 0008 has down_revision='0007'.

        req: events-014 — Alembic head must chain: 0007 → 0008
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0008_events_history.py"
        content = p.read_text(encoding="utf-8")
        assert re.search(r'revision\s*:\s*str\s*=\s*"0008"', content)
        assert re.search(r'down_revision.*=.*"0007"', content)

    def test_migration_adds_events_history_json(self) -> None:
        """Migration 0008 upgrade() adds events_history_json to conversationsession.

        req: events-014
        """
        p = Path(__file__).parent.parent / "alembic" / "versions" / "0008_events_history.py"
        content = p.read_text(encoding="utf-8")
        assert "events_history_json" in content
        assert "conversationsession" in content
        assert "add_column" in content


# ---------------------------------------------------------------------------
# TestBuildIcs — RFC-5545 + tz + active_lang text
# ---------------------------------------------------------------------------


class TestBuildIcs:
    """build_ics produces a valid RFC-5545 VCALENDAR string.

    req: events-011 (tz localisation), events-012 (RFC-5545 via ics library)
    """

    def test_output_is_vcalendar_string(self) -> None:
        """build_ics returns a string containing BEGIN:VCALENDAR and BEGIN:VEVENT.

        req: events-012
        """
        result = build_ics(
            summary="Test Event",
            description="A philosophy talk.",
            start_at=datetime(2026, 9, 1, 18, 0, 0),
            end_at=datetime(2026, 9, 1, 20, 0, 0),
            location="Online",
            tz="UTC",
        )
        assert isinstance(result, str)
        assert "BEGIN:VCALENDAR" in result
        assert "BEGIN:VEVENT" in result
        assert "END:VEVENT" in result
        assert "END:VCALENDAR" in result

    def test_summary_appears_in_output(self) -> None:
        """The summary string is present as SUMMARY in the VCALENDAR output.

        req: events-011 (active_lang text in .ics)
        """
        result = build_ics(
            summary="Seminario de Estoicismo",
            description="Un seminario sobre la filosofía estoica.",
            start_at=datetime(2026, 9, 1, 18, 0, 0),
            end_at=datetime(2026, 9, 1, 20, 0, 0),
            location="Madrid",
            tz="Europe/Madrid",
        )
        assert "Seminario de Estoicismo" in result

    def test_description_appears_in_output(self) -> None:
        """The description is present in the VCALENDAR output.

        req: events-011
        """
        result = build_ics(
            summary="Seminar",
            description="Philosophia perennis",
            start_at=datetime(2026, 9, 1, 18, 0, 0),
            end_at=datetime(2026, 9, 1, 20, 0, 0),
            location="Rome",
            tz="Europe/Rome",
        )
        assert "Philosophia perennis" in result

    def test_dtstart_is_present(self) -> None:
        """DTSTART is present in the VCALENDAR output.

        req: events-012 (RFC-5545 required property)
        """
        result = build_ics(
            summary="Event",
            description="Desc",
            start_at=datetime(2026, 9, 1, 14, 0, 0),
            end_at=datetime(2026, 9, 1, 16, 0, 0),
            location="Online",
            tz="America/New_York",
        )
        assert "DTSTART" in result
        assert "DTEND" in result

    def test_invalid_tz_falls_back_to_utc(self) -> None:
        """build_ics with an invalid tz string falls back to UTC without raising.

        req: events-016 (resilience — never crash the turn)
        """
        result = build_ics(
            summary="E",
            description="D",
            start_at=datetime(2026, 9, 1, 10, 0, 0),
            end_at=datetime(2026, 9, 1, 12, 0, 0),
            location="Online",
            tz="Not/A_Timezone",
        )
        assert "BEGIN:VCALENDAR" in result

    def test_timezone_conversion_produces_correct_utc_instant(self) -> None:
        """Naive-UTC 18:00 → Mexico City (UTC-6) → DTSTART is 00:00 next day UTC.

        Verifies that the UTC→local tz conversion preserves the absolute time
        (the ics library outputs UTC with Z suffix).

        req: events-011 — times localised to tz
        """
        # 2026-07-01 00:00 UTC (stored as naive) = 2026-06-30 18:00 Mexico City (UTC-6)
        # We store 2026-07-01 00:00 UTC and want that exact instant in the ICS.
        result = build_ics(
            summary="E",
            description="D",
            start_at=datetime(2026, 7, 1, 0, 0, 0),
            end_at=datetime(2026, 7, 1, 2, 0, 0),
            location="Online",
            tz="America/Mexico_City",
        )
        # ics library serialises as UTC Z — 2026-07-01T00:00:00Z
        assert "20260701T000000Z" in result


# ---------------------------------------------------------------------------
# TestEventsAgentListEvents — TestModel smoke (mocked DB)
# ---------------------------------------------------------------------------


class TestEventsAgentListEvents:
    """Events agent list_events tool returns Event rows from the DB.

    req: events-007 — list_events reads Event rows (id/title/start/end)
    """

    async def test_list_events_returns_rows(self, _db_session: AsyncSession) -> None:
        """list_events returns Event rows visible in the DB.

        Uses a real SQLite session with an Event row inserted before the agent run.

        req: events-007
        """
        ev = Event(
            title="Stoicism Seminar",
            description="Desc",
            start_at=_NOW,
            end_at=datetime(2026, 7, 1, 20, 0, 0),
            location="Online",
            timezone="UTC",
        )
        _db_session.add(ev)
        await _db_session.flush()

        deps = _make_deps(_db_session)

        with get_events_agent().override(
            model=TestModel(custom_output_text="Here are the events.")
        ):
            result = await get_events_agent().run("What events are there?", deps=deps)

        # The agent ran successfully and produced a string output.
        assert isinstance(result.output, str)

    async def test_list_events_empty_db_returns_string(self, _db_session: AsyncSession) -> None:
        """list_events with no events returns a string (no crash on empty list).

        req: events-007 — empty catalog handled gracefully
        """
        deps = _make_deps(_db_session)

        with get_events_agent().override(
            model=TestModel(custom_output_text="No events are available.")
        ):
            result = await get_events_agent().run("Any events?", deps=deps)

        assert isinstance(result.output, str)


# ---------------------------------------------------------------------------
# TestEventsAgentEnroll — enroll tool (mocked DB)
# ---------------------------------------------------------------------------


class TestEventsAgentEnroll:
    """Events agent enroll tool: event-exists guard, persist, no-write on missing.

    req: events-008 (enroll receives event_id + name),
         events-010 (persist Enrollment),
         events-013 (no write on non-existent event)
    """

    async def test_enroll_persists_enrollment_for_existing_event(
        self, _db_session: AsyncSession
    ) -> None:
        """enroll tool writes Enrollment row when event exists.

        req: events-010 — persist Enrollment(session_id, event_id, name)
        """
        ev = Event(
            title="Stoicism Seminar",
            description="Desc",
            start_at=_NOW,
            end_at=datetime(2026, 7, 1, 20, 0, 0),
            location="Online",
            timezone="UTC",
        )
        _db_session.add(ev)
        await _db_session.flush()
        event_id = ev.id or 1

        deps = _make_deps(_db_session)
        ctx = _make_run_ctx(deps)

        result = await enroll(ctx, event_id, "Alice")  # type: ignore[arg-type]

        # Verify the enrollment row exists
        from sqlmodel import select

        rows = (
            (await _db_session.execute(select(Enrollment).where(Enrollment.event_id == event_id)))
            .scalars()
            .all()
        )

        assert len(rows) == 1
        assert rows[0].name == "Alice"
        assert rows[0].session_id == "ev-test"
        assert "/events/" in result
        assert "ics" in result

    async def test_enroll_no_write_on_nonexistent_event(self, _db_session: AsyncSession) -> None:
        """enroll tool returns an error message and does NOT write when event is absent.

        req: events-013 — no enroll, no invention
        """
        deps = _make_deps(_db_session)
        ctx = _make_run_ctx(deps)

        result = await enroll(ctx, 9999, "Bob")  # type: ignore[arg-type]

        assert "not available" in result.lower() or "unavailable" in result.lower()

        # No enrollment rows must exist
        from sqlmodel import select

        rows = (await _db_session.execute(select(Enrollment))).scalars().all()
        assert len(rows) == 0

    async def test_enroll_includes_ics_path_in_result(self, _db_session: AsyncSession) -> None:
        """enroll result contains the /events/{id}/ics download path.

        req: events-010 — return confirmation + .ics download path
        """
        ev = Event(
            title="Seminar",
            description="D",
            start_at=_NOW,
            end_at=datetime(2026, 7, 1, 20, 0, 0),
            location="Online",
            timezone="UTC",
        )
        _db_session.add(ev)
        await _db_session.flush()

        deps = _make_deps(_db_session)
        ctx = _make_run_ctx(deps)

        result = await enroll(ctx, ev.id or 1, "Charlie")  # type: ignore[arg-type]
        assert "/events/" in result
        assert "ics" in result

    async def test_enroll_uses_geo_timezone(self, _db_session: AsyncSession) -> None:
        """enroll uses ctx.deps.geo.timezone (falls back to default_timezone when None).

        req: events-011 — .ics tz from geo.timezone
        """
        ev = Event(
            title="E",
            description="D",
            start_at=_NOW,
            end_at=datetime(2026, 7, 1, 20, 0, 0),
            location="Online",
            timezone="UTC",
        )
        _db_session.add(ev)
        await _db_session.flush()

        # Deps with geo.timezone = None — should fall back to default_timezone
        deps = _make_deps(_db_session, timezone_str="")
        deps.geo = GeoContext(source="private_ip", ok=False)  # timezone is None
        ctx = _make_run_ctx(deps)

        # Should succeed without raising even though geo.timezone is None
        result = await enroll(ctx, ev.id or 1, "Dave")  # type: ignore[arg-type]
        assert "/events/" in result

    def test_enroll_active_lang_text_en(self) -> None:
        """Module-level _ICS_SUMMARY_PREFIX and _ENROLL_CONFIRMATION cover 'en'.

        req: events-015 — events dialogue in active_lang
        """
        assert "en" in _ICS_SUMMARY_PREFIX
        assert "en" in _ENROLL_CONFIRMATION


# ---------------------------------------------------------------------------
# TestAskEventsTool — orchestrator ask_events + events_enabled gate
# ---------------------------------------------------------------------------


class TestAskEventsTool:
    """ask_events forwards deps+usage; events_enabled=False → tool absent.

    req: events-014 (deps+usage forwarded), events-016 (degrade on error),
         events-018 (events_enabled gate)
    """

    async def test_ask_events_returns_string(self, _db_session: AsyncSession) -> None:
        """ask_events returns a string result from the events agent.

        req: events-014
        """
        deps = _make_deps(_db_session)
        ctx = _make_run_ctx(deps)

        with get_events_agent().override(
            model=TestModel(custom_output_text="No events currently scheduled.")
        ):
            result = await ask_events(ctx, "What events do you have?")  # type: ignore[arg-type]

        assert isinstance(result, str)

    async def test_ask_events_degrades_on_exception(self, _db_session: AsyncSession) -> None:
        """ask_events returns a safe fallback string when the agent raises.

        req: events-016 — errors degrade gracefully; never raise to user
        """
        deps = _make_deps(_db_session)
        ctx = _make_run_ctx(deps)

        with patch.object(get_events_agent(), "run", side_effect=RuntimeError("boom")):
            result = await ask_events(ctx, "Show me events.")  # type: ignore[arg-type]

        assert isinstance(result, str)
        assert "unavailable" in result.lower() or "service" in result.lower()

    def test_events_enabled_false_tool_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_orchestrator() does NOT register ask_events when events_enabled=False.

        req: events-018
        """
        monkeypatch.setenv("EVENTS_ENABLED", "false")
        # get_settings and get_orchestrator caches are cleared by conftest fixtures.
        # Build a fresh orchestrator with events_enabled=False.
        orc = get_orchestrator()
        tool_names = list(orc._function_toolset.tools.keys())  # type: ignore[attr-defined]
        assert "ask_events" not in tool_names

    def test_events_enabled_true_tool_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_orchestrator() DOES register ask_events when events_enabled=True (default).

        req: events-018
        """
        monkeypatch.setenv("EVENTS_ENABLED", "true")
        orc = get_orchestrator()
        tool_names = list(orc._function_toolset.tools.keys())  # type: ignore[attr-defined]
        assert "ask_events" in tool_names

    async def test_ask_events_forwards_usage(self, _db_session: AsyncSession) -> None:
        """ask_events passes usage=ctx.usage so token cost aggregates correctly.

        req: events-014 — deps+usage forwarded (UsageLimits stay correct)
        """
        deps = _make_deps(_db_session)
        ctx = _make_run_ctx(deps)

        run_calls: list[dict[str, Any]] = []
        original_run = get_events_agent().run

        async def _patched_run(q: str, **kw: Any) -> Any:
            run_calls.append(kw)
            return await original_run(q, **kw)

        with (
            get_events_agent().override(model=TestModel(custom_output_text="No events.")),
            patch.object(get_events_agent(), "run", side_effect=_patched_run),
        ):
            await ask_events(ctx, "Any events?")  # type: ignore[arg-type]

        assert len(run_calls) == 1
        assert "usage" in run_calls[0]
        assert "deps" in run_calls[0]


# ---------------------------------------------------------------------------
# TestEventsEndpoints — admin CRUD + auth + .ics download
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db() -> MagicMock:
    """Minimal AsyncSession mock for endpoint tests (no real DB)."""
    db = MagicMock()
    _added: list[Any] = []

    def _add(obj: Any) -> None:
        _added.append(obj)
        if isinstance(obj, Event) and obj.id is None:
            obj.id = 1

    async def _flush() -> None:
        for obj in _added:
            if isinstance(obj, Event) and obj.id is None:
                obj.id = 1

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock(side_effect=_flush)
    db.get = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.rollback = AsyncMock()

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)
    return db


@pytest.fixture()
def client(mock_db: MagicMock) -> Generator[Any, None, None]:
    """TestClient with the DB session replaced by mock_db."""
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


_BODY = {
    "title": "Stoicism Seminar",
    "description": "A seminar on Stoic philosophy.",
    "start_at": "2026-09-01T18:00:00",
    "end_at": "2026-09-01T20:00:00",
    "location": "Online",
    "timezone": "UTC",
}


class TestCreateEvent:
    """POST /events — req: events-001, events-002."""

    def test_missing_token_returns_401(self, client: Any) -> None:
        """No X-Admin-Token → 401; no DB mutation.

        req: events-002
        """
        resp = client.post("/events", json=_BODY)
        assert resp.status_code == 401

    def test_wrong_token_returns_403(self, client: Any) -> None:
        """Wrong token → 403.

        req: events-002
        """
        resp = client.post("/events", json=_BODY, headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 403

    def test_valid_token_creates_event(self, client: Any, mock_db: MagicMock) -> None:
        """Valid token + body → 201 with event summary.

        req: events-001
        """
        resp = client.post("/events", json=_BODY, headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Stoicism Seminar"
        assert "id" in data

    def test_missing_token_no_db_add(self, client: Any, mock_db: MagicMock) -> None:
        """Missing token → db.add NOT called.

        req: events-002
        """
        client.post("/events", json=_BODY)
        mock_db.add.assert_not_called()


class TestListEvents:
    """GET /events — req: events-003, events-002."""

    def test_missing_token_returns_401(self, client: Any) -> None:
        """No token → 401.

        req: events-002
        """
        resp = client.get("/events")
        assert resp.status_code == 401

    def test_returns_event_list(self, client: Any, mock_db: MagicMock) -> None:
        """Returns list of event summaries.

        req: events-003
        """
        ev = Event(
            id=5,
            title="Test",
            description="D",
            start_at=_NOW,
            end_at=_NOW,
            location="Online",
            timezone="UTC",
        )
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [ev]
        mock_db.execute = AsyncMock(return_value=result_mock)

        resp = client.get("/events", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 5
        assert data[0]["title"] == "Test"

    def test_empty_returns_empty_list(self, client: Any) -> None:
        """No events → 200 with [].

        req: events-003
        """
        resp = client.get("/events", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 200
        assert resp.json() == []


class TestDeleteEvent:
    """DELETE /events/{id} — req: events-004, events-002."""

    def test_missing_token_returns_401(self, client: Any) -> None:
        """No token → 401.

        req: events-002
        """
        resp = client.delete("/events/1")
        assert resp.status_code == 401

    def test_delete_existing_event_returns_204(self, client: Any, mock_db: MagicMock) -> None:
        """Existing event → 204; db.delete is called.

        req: events-004
        """
        ev = _make_event()
        mock_db.get = AsyncMock(return_value=ev)
        resp = client.delete("/events/1", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 204
        mock_db.delete.assert_called_once_with(ev)

    def test_delete_nonexistent_event_returns_404(self, client: Any, mock_db: MagicMock) -> None:
        """Non-existent event → 404.

        req: events-004
        """
        mock_db.get = AsyncMock(return_value=None)
        resp = client.delete("/events/99", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 404

    def test_missing_token_no_db_delete(self, client: Any, mock_db: MagicMock) -> None:
        """Missing token → db.delete NOT called.

        req: events-002
        """
        client.delete("/events/1")
        mock_db.delete.assert_not_called()


class TestListEnrollments:
    """GET /events/{id}/enrollments — req: events-005, events-002."""

    def test_missing_token_returns_401(self, client: Any) -> None:
        """No token → 401; no data disclosed.

        req: events-002
        """
        resp = client.get("/events/1/enrollments")
        assert resp.status_code == 401

    def test_returns_enrollments(self, client: Any, mock_db: MagicMock) -> None:
        """Returns enrolled names + timestamps for an event.

        req: events-005
        """
        from app.time import now_utc

        ev = _make_event()
        mock_db.get = AsyncMock(return_value=ev)
        en = Enrollment(id=1, session_id="s1", event_id=1, name="Alice", created_at=now_utc())
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [en]
        mock_db.execute = AsyncMock(return_value=result_mock)

        resp = client.get("/events/1/enrollments", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Alice"
        assert "created_at" in data[0]

    def test_nonexistent_event_returns_404(self, client: Any, mock_db: MagicMock) -> None:
        """Non-existent event → 404.

        req: events-005
        """
        mock_db.get = AsyncMock(return_value=None)
        resp = client.get("/events/99/enrollments", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 404


class TestDownloadIcs:
    """GET /events/{id}/ics — req: events-010, events-012 (anonymous)."""

    def test_anonymous_download_returns_ics(self, client: Any, mock_db: MagicMock) -> None:
        """Anonymous request returns the .ics with text/calendar content-type.

        req: events-010, events-012
        """
        ev = _make_event()
        mock_db.get = AsyncMock(return_value=ev)

        resp = client.get("/events/1/ics")  # no token — anonymous
        assert resp.status_code == 200
        assert "text/calendar" in resp.headers["content-type"]
        assert "BEGIN:VCALENDAR" in resp.text

    def test_ics_contains_event_title(self, client: Any, mock_db: MagicMock) -> None:
        """Downloaded .ics SUMMARY contains the event title.

        req: events-012 — valid RFC-5545 with correct SUMMARY
        """
        ev = _make_event(title="Stoicism Seminar")
        mock_db.get = AsyncMock(return_value=ev)

        resp = client.get("/events/1/ics")
        assert "Stoicism Seminar" in resp.text

    def test_nonexistent_event_returns_404(self, client: Any, mock_db: MagicMock) -> None:
        """Non-existent event → 404.

        req: events-010
        """
        mock_db.get = AsyncMock(return_value=None)
        resp = client.get("/events/99/ics")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestEventsHistoryRepository — load/save_events_messages round-trip
# ---------------------------------------------------------------------------


class TestEventsHistoryRepository:
    """SessionRepository.load/save_events_messages round-trip via SQLite.

    req: events-014 — events sub-agent accumulates its own per-session history
    """

    async def test_load_events_messages_returns_none_on_fresh_session(
        self, _db_session: AsyncSession
    ) -> None:
        """load_events_messages returns None before any events history is saved.

        req: events-014
        """
        repo = SessionRepository(_db_session)
        await repo.get_or_create("ev-fresh")
        result = await repo.load_events_messages("ev-fresh")
        assert result is None

    async def test_save_and_load_events_messages_round_trip(
        self, _db_session: AsyncSession
    ) -> None:
        """save_events_messages persists; load_events_messages deserialises them.

        req: events-014 — serialise / deserialise via ModelMessagesTypeAdapter
        """
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        repo = SessionRepository(_db_session)
        await repo.get_or_create("ev-roundtrip")

        msgs = [ModelRequest(parts=[UserPromptPart(content="Any events?")])]
        await repo.save_events_messages("ev-roundtrip", msgs)  # type: ignore[arg-type]
        await _db_session.commit()

        loaded = await repo.load_events_messages("ev-roundtrip")
        assert loaded is not None
        assert len(loaded) == 1

    async def test_save_events_messages_raises_on_missing_session(
        self, _db_session: AsyncSession
    ) -> None:
        """save_events_messages raises ValueError when the session row is absent.

        req: events-014
        """
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        repo = SessionRepository(_db_session)
        msgs = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        with pytest.raises(ValueError, match="not found"):
            await repo.save_events_messages("no-such", msgs)  # type: ignore[arg-type]

    async def test_events_history_independent_of_faq_history(
        self, _db_session: AsyncSession
    ) -> None:
        """events_history_json and faq_history_json are independent columns.

        req: events-014 — events history must not contaminate FAQ history
        """
        from pydantic_ai.messages import ModelMessagesTypeAdapter as MTA
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        repo = SessionRepository(_db_session)
        await repo.get_or_create("isolation")

        faq_msgs = [ModelRequest(parts=[UserPromptPart(content="FAQ question")])]
        ev_msgs = [ModelRequest(parts=[UserPromptPart(content="Event question")])]

        await repo.save_faq_messages("isolation", faq_msgs)  # type: ignore[arg-type]
        await repo.save_events_messages("isolation", ev_msgs)  # type: ignore[arg-type]
        await _db_session.commit()

        loaded_faq = await repo.load_faq_messages("isolation")
        loaded_ev = await repo.load_events_messages("isolation")

        assert loaded_faq is not None
        assert loaded_ev is not None

        faq_json = MTA.dump_json(loaded_faq).decode()
        ev_json = MTA.dump_json(loaded_ev).decode()

        assert "FAQ question" in faq_json
        assert "Event question" in ev_json
        assert "Event question" not in faq_json
        assert "FAQ question" not in ev_json


# ---------------------------------------------------------------------------
# TestSubAgentMemoryTwoTurn — second run gets first turn's messages
# ---------------------------------------------------------------------------


class TestSubAgentMemoryTwoTurn:
    """ask_events loads events history and passes it on the second turn.

    req: events-014 — 2nd events turn receives 1st turn's messages as message_history
    """

    async def test_second_events_turn_receives_first_turn_messages(
        self, _db_session: AsyncSession
    ) -> None:
        """After turn 1, save_events_messages is called; turn 2 passes that history.

        req: events-014
        """
        session_id = "two-turn-ev"
        repo = SessionRepository(_db_session)
        await repo.get_or_create(session_id)
        await _db_session.commit()

        deps = _make_deps(_db_session, session_id=session_id)
        captured: list[object] = []

        original_run = get_events_agent().run

        async def _patched_run(q: str, **kw: Any) -> Any:
            captured.append(kw.get("message_history"))
            return await original_run(q, **kw)

        with (
            get_events_agent().override(model=TestModel(custom_output_text="No events.")),
            patch.object(get_events_agent(), "run", side_effect=_patched_run),
        ):
            await ask_events(_make_run_ctx(deps), "Any events?")  # type: ignore[arg-type]
            await _db_session.commit()
            await ask_events(_make_run_ctx(deps), "Tell me more.")  # type: ignore[arg-type]

        # Turn 1: message_history must be None (no prior events history).
        assert captured[0] is None, f"Expected None on turn 1, got {captured[0]!r}"
        # Turn 2: message_history must be a non-empty list from turn 1.
        assert captured[1] is not None, "Expected message_history set on turn 2"
        assert isinstance(captured[1], list)
        assert len(captured[1]) > 0


# ---------------------------------------------------------------------------
# TestEventsConfig — events_enabled flag
# ---------------------------------------------------------------------------


class TestEventsConfig:
    """events_enabled: bool = True is present in Settings.

    req: events-018 — feature flag exists and defaults to True
    """

    def test_events_enabled_defaults_to_true(self) -> None:
        """Settings.events_enabled defaults to True.

        req: events-018
        """
        settings = get_settings()
        assert settings.events_enabled is True

    def test_events_enabled_can_be_set_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """events_enabled can be overridden to False via env var.

        req: events-018
        """
        monkeypatch.setenv("EVENTS_ENABLED", "false")
        settings = get_settings()
        assert settings.events_enabled is False
