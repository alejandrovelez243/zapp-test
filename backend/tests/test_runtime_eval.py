"""Tests for app/eval/runtime.py — is_goodbye, evaluate_conversation, idle_sweep_once.

Uses TestModel (no gateway calls) and in-memory aiosqlite (no Postgres).

Covers: evaluation-014, evaluation-015, evaluation-016, evaluation-017,
        evaluation-018, evaluation-019
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select

from app.agents.session import (
    ConversationSession,
    SessionGrade,
)
from app.eval.runtime import evaluate_conversation, idle_sweep_once, is_goodbye
from evals.judge import get_judge

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Module-level fixture: clear the judge lru_cache around every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_judge_cache() -> Generator[None, None, None]:
    """Clear get_judge lru_cache before and after each test.

    Ensures the agent is built fresh (with the dummy key from conftest) and
    TestModel overrides take effect cleanly.
    """
    get_judge.cache_clear()
    yield
    get_judge.cache_clear()


# ---------------------------------------------------------------------------
# DB fixture: in-memory SQLite with both SQLModel tables
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_session(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh in-memory SQLite AsyncSession with all tables created.

    Sets DATABASE_URL and ADMIN_TOKEN so get_settings() can build Settings
    without raising (the conftest autouse fixture clears the settings cache
    before each test so these patches are always visible to the first call).
    """
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")

    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# is_goodbye (evaluation-015)
# ---------------------------------------------------------------------------


def test_is_goodbye_es_positive() -> None:
    """Spanish goodbye phrase → True. (evaluation-015)"""
    assert is_goodbye("no necesito más ayuda", "es") is True


def test_is_goodbye_en_positive() -> None:
    """English goodbye keyword → True. (evaluation-015)"""
    assert is_goodbye("goodbye, thanks!", "en") is True


def test_is_goodbye_pt_positive() -> None:
    """Portuguese goodbye keyword → True. (evaluation-015)"""
    assert is_goodbye("tchau, obrigado!", "pt") is True


def test_is_goodbye_negative() -> None:
    """Non-goodbye message → False. (evaluation-015)"""
    assert is_goodbye("What time is the stoicism seminar?", "en") is False


def test_is_goodbye_no_lang_searches_all() -> None:
    """lang=None → all keyword lists searched; Spanish keyword detected. (evaluation-015)"""
    assert is_goodbye("adiós y gracias", None) is True


# ---------------------------------------------------------------------------
# evaluate_conversation (evaluation-016, evaluation-017)
# ---------------------------------------------------------------------------


async def test_evaluate_conversation_persists_grade(
    db_session: AsyncSession,
) -> None:
    """evaluate_conversation with TestModel(custom_output_args=2) persists
    score=2, needs_review=True, and sets graded_at on the session row.

    Covers evaluation-016 (persist grade) and evaluation-017 (observability
    emitted without error — PostHog and Logfire are no-ops in tests).
    """
    session_id = "test-session-grade-001"

    # Seed a ConversationSession (history_json=None → transcript="(no messages)").
    now = datetime.now(UTC).replace(tzinfo=None)
    session_row = ConversationSession(id=session_id, created_at=now, updated_at=now)
    db_session.add(session_row)
    await db_session.commit()

    # Override the judge to return score=2 deterministically (no gateway call).
    with get_judge().override(model=TestModel(custom_output_args=2)):
        await evaluate_conversation(db_session, session_id)

    # Verify SessionGrade persisted with the correct score and review flag.
    grade_result = await db_session.execute(
        select(SessionGrade).where(SessionGrade.session_id == session_id)
    )
    grade = grade_result.scalar_one_or_none()
    assert grade is not None, "SessionGrade row must be persisted (evaluation-016)"
    assert grade.score == 2
    # 2 < THRESHOLDS["judge_mean"] == 4.0 → needs_review must be True.
    assert grade.needs_review is True

    # Verify graded_at set on the session (sweep guard — evaluation-016).
    await db_session.refresh(session_row)
    assert session_row.graded_at is not None, "graded_at must be set after grading"


# ---------------------------------------------------------------------------
# idle_sweep_once (evaluation-014, evaluation-018, evaluation-019)
# ---------------------------------------------------------------------------


async def test_idle_sweep_grades_idle_ungraded_session(
    db_session: AsyncSession,
) -> None:
    """Sessions idle > timeout AND graded_at IS NULL are graded by the sweep.

    (evaluation-014)
    """
    session_id = "sweep-idle-001"

    # Create a session whose updated_at is 950 s ago — beyond the 900 s default.
    old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=950)
    session_row = ConversationSession(id=session_id, created_at=old_time, updated_at=old_time)
    db_session.add(session_row)
    await db_session.commit()

    with get_judge().override(model=TestModel(custom_output_args=3)):
        count = await idle_sweep_once(db_session)

    assert count == 1, "Exactly one idle session should be graded"

    grade_result = await db_session.execute(
        select(SessionGrade).where(SessionGrade.session_id == session_id)
    )
    assert grade_result.scalar_one_or_none() is not None


async def test_idle_sweep_skips_already_graded(
    db_session: AsyncSession,
) -> None:
    """Sessions with graded_at IS NOT NULL are skipped by the sweep.

    This ensures already-evaluated sessions are never re-graded.
    (evaluation-014, evaluation-019)
    """
    session_id = "sweep-already-graded-001"
    old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=950)
    graded_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=100)

    session_row = ConversationSession(
        id=session_id,
        created_at=old_time,
        updated_at=old_time,
        graded_at=graded_time,  # already graded
    )
    db_session.add(session_row)
    await db_session.commit()

    with get_judge().override(model=TestModel(custom_output_args=3)):
        count = await idle_sweep_once(db_session)

    assert count == 0, "Already-graded session must not be re-graded"

    # Confirm no new SessionGrade row was created.
    grade_result = await db_session.execute(
        select(SessionGrade).where(SessionGrade.session_id == session_id)
    )
    assert grade_result.scalar_one_or_none() is None


async def test_idle_sweep_skips_recent_session(
    db_session: AsyncSession,
) -> None:
    """Sessions updated recently (< timeout seconds ago) are NOT graded. (evaluation-014)"""
    session_id = "sweep-recent-001"
    # 100 s ago — well below the 900 s default timeout.
    recent_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=100)

    session_row = ConversationSession(id=session_id, created_at=recent_time, updated_at=recent_time)
    db_session.add(session_row)
    await db_session.commit()

    with get_judge().override(model=TestModel(custom_output_args=3)):
        count = await idle_sweep_once(db_session)

    assert count == 0, "Recent session must not be treated as idle"


async def test_idle_sweep_disabled_skips_grading(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When runtime_eval_enabled=False, idle_sweep_once returns 0 immediately.

    (evaluation-018)
    """
    monkeypatch.setenv("RUNTIME_EVAL_ENABLED", "false")

    session_id = "sweep-disabled-001"
    old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=950)
    session_row = ConversationSession(id=session_id, created_at=old_time, updated_at=old_time)
    db_session.add(session_row)
    await db_session.commit()

    with get_judge().override(model=TestModel(custom_output_args=3)):
        count = await idle_sweep_once(db_session)

    assert count == 0, "Sweep must be disabled when runtime_eval_enabled=False"

    grade_result = await db_session.execute(
        select(SessionGrade).where(SessionGrade.session_id == session_id)
    )
    assert grade_result.scalar_one_or_none() is None
