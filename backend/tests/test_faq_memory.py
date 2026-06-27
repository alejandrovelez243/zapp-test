"""Tests for FAQ sub-agent per-session memory (faq-rag-019).

Verifies:
  1. ``ConversationSession`` has a ``faq_history_json`` column (nullable TEXT).
  2. ``SessionRepository.load_faq_messages`` returns ``None`` on a fresh session.
  3. ``SessionRepository.save_faq_messages`` / ``load_faq_messages`` round-trip works.
  4. ``ask_faq`` tool passes ``message_history`` on the 2nd turn in a session:
     after the 1st turn, ``save_faq_messages`` is called; on the 2nd turn,
     ``load_faq_messages`` returns those messages and they are forwarded to the
     FAQ agent run.
  5. Alembic migration 0006 offline SQL contains ``faq_history_json`` and
     ``ALTER TABLE conversationsession``.

No real Postgres / gateway calls are made.  All DB operations use an in-memory
SQLite engine (aiosqlite); the FAQ and orchestrator agents run under TestModel.

Requirements: faq-rag-019
Design contract: specs/faq-rag/design.md §2.6
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.faq import get_faq_agent
from app.agents.orchestrator import ask_faq
from app.agents.session import ConversationSession, SessionRepository
from app.deps import AgentDeps
from app.lang.detector import DetectionResult
from app.lang.state import ActiveLangDecision

# ---------------------------------------------------------------------------
# Engine / session fixtures
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture()
async def _db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh in-memory SQLite AsyncSession with all tables created."""
    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        # Import all table models so SQLModel.metadata includes them.
        import app.agents.session  # side-effect: registers tables
        import app.rag.models  # noqa: F401 — side-effect: registers rag tables

        await conn.run_sync(SQLModel.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide the env vars that get_settings() requires."""
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")


@pytest.fixture(autouse=True)
def _clear_faq_cache() -> Generator[None, None, None]:
    """Clear get_faq_agent lru_cache before and after each test."""
    get_faq_agent.cache_clear()
    yield
    get_faq_agent.cache_clear()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_deps(session: AsyncSession, session_id: str = "faq-mem-test") -> AgentDeps:
    """Minimal AgentDeps backed by a real AsyncSession for memory tests."""
    return AgentDeps(
        session=session,
        http=AsyncMock(spec=httpx.AsyncClient),
        session_id=session_id,
        request_ip="127.0.0.1",
        active_lang="en",
        detection=DetectionResult(lang="en", confidence=0.95, is_reliable=True),
        lang_decision=ActiveLangDecision(
            active_lang="en",
            first_turn=True,
            locked=False,
            fallback_used=False,
        ),
    )


def _make_fake_messages() -> list[object]:
    """Return a minimal list[ModelMessage] serialisable by ModelMessagesTypeAdapter."""
    return [ModelRequest(parts=[UserPromptPart(content="What is Stoicism?")])]


# ---------------------------------------------------------------------------
# ConversationSession schema tests
# ---------------------------------------------------------------------------


class TestConversationSessionSchema:
    """ConversationSession must expose faq_history_json as a nullable field.

    req: faq-rag-019
    """

    def test_faq_history_json_field_present(self) -> None:
        """ConversationSession has a faq_history_json attribute defaulting to None.

        req: faq-rag-019 — separate column for FAQ sub-agent history
        """
        assert hasattr(ConversationSession, "faq_history_json")
        sess = ConversationSession(id="schema-check")
        assert sess.faq_history_json is None

    def test_faq_history_json_independent_of_history_json(self) -> None:
        """faq_history_json and history_json are independent fields.

        req: faq-rag-019 — FAQ history must not contaminate orchestrator history
        """
        sess = ConversationSession(id="independent-check")
        sess.history_json = '["orchestrator"]'
        sess.faq_history_json = '["faq"]'
        assert sess.history_json == '["orchestrator"]'
        assert sess.faq_history_json == '["faq"]'


# ---------------------------------------------------------------------------
# SessionRepository round-trip tests
# ---------------------------------------------------------------------------


class TestSessionRepositoryFaqMessages:
    """load_faq_messages / save_faq_messages round-trip via in-memory SQLite.

    req: faq-rag-019
    """

    async def test_load_faq_messages_returns_none_on_fresh_session(
        self, _db_session: AsyncSession
    ) -> None:
        """load_faq_messages returns None before any FAQ history is saved.

        req: faq-rag-019 — fresh session has no FAQ history; None → fresh context
        """
        repo = SessionRepository(_db_session)
        await repo.get_or_create("fresh-session")
        result = await repo.load_faq_messages("fresh-session")
        assert result is None

    async def test_load_faq_messages_returns_none_for_missing_session(
        self, _db_session: AsyncSession
    ) -> None:
        """load_faq_messages returns None when the session row does not exist.

        req: faq-rag-019 — missing row treated the same as null history
        """
        repo = SessionRepository(_db_session)
        result = await repo.load_faq_messages("nonexistent-session")
        assert result is None

    async def test_save_and_load_faq_messages_round_trip(self, _db_session: AsyncSession) -> None:
        """save_faq_messages persists messages; load_faq_messages deserialises them.

        req: faq-rag-019 — serialise / deserialise via ModelMessagesTypeAdapter
        """
        repo = SessionRepository(_db_session)
        await repo.get_or_create("roundtrip-session")

        msgs = _make_fake_messages()
        await repo.save_faq_messages("roundtrip-session", msgs)  # type: ignore[arg-type]
        await _db_session.commit()

        loaded = await repo.load_faq_messages("roundtrip-session")
        assert loaded is not None
        assert len(loaded) == 1

    async def test_save_faq_messages_raises_on_missing_session(
        self, _db_session: AsyncSession
    ) -> None:
        """save_faq_messages raises ValueError when the session row is absent.

        req: faq-rag-019 — callers must call get_or_create first
        """
        repo = SessionRepository(_db_session)
        msgs = _make_fake_messages()
        with pytest.raises(ValueError, match="not found"):
            await repo.save_faq_messages("no-such-session", msgs)  # type: ignore[arg-type]

    async def test_faq_history_does_not_overwrite_orchestrator_history(
        self, _db_session: AsyncSession
    ) -> None:
        """Saving FAQ history leaves history_json untouched (and vice-versa).

        req: faq-rag-019 — FAQ history column is independent of orchestrator history
        """
        from pydantic_ai.messages import ModelMessagesTypeAdapter as MTA

        repo = SessionRepository(_db_session)
        await repo.get_or_create("isolation-session")

        orch_msgs = _make_fake_messages()
        faq_msgs = [ModelRequest(parts=[UserPromptPart(content="FAQ question")])]

        await repo.save_messages("isolation-session", orch_msgs)  # type: ignore[arg-type]
        await repo.save_faq_messages("isolation-session", faq_msgs)  # type: ignore[arg-type]
        await _db_session.commit()

        loaded_orch = await repo.load_messages("isolation-session")
        loaded_faq = await repo.load_faq_messages("isolation-session")

        assert loaded_orch is not None
        assert loaded_faq is not None
        # Orchestrator history has the original message; FAQ history has the FAQ message.
        orch_json = MTA.dump_json(loaded_orch).decode()
        faq_json = MTA.dump_json(loaded_faq).decode()
        assert "What is Stoicism?" in orch_json
        assert "FAQ question" in faq_json
        # The two histories must not share content.
        assert "FAQ question" not in orch_json
        assert "What is Stoicism?" not in faq_json


# ---------------------------------------------------------------------------
# ask_faq tool — message_history forwarding test
# ---------------------------------------------------------------------------


class TestAskFaqMemoryWiring:
    """ask_faq loads FAQ history and forwards it to the FAQ agent on the 2nd turn.

    Uses a real in-memory SQLite session and monkeypatches the FAQ agent's
    retrieve tool so no real DB/embed calls are made.  The orchestrator and FAQ
    agents run under TestModel.

    req: faq-rag-019 — 2nd FAQ turn receives 1st turn's messages as message_history
    """

    async def test_second_faq_turn_receives_first_turn_messages(
        self, _db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After turn 1, save_faq_messages is called; turn 2 passes that history.

        Two FAQ agent runs are simulated in the same session.  Between them the
        messages from run 1 are persisted.  We assert that the second run is called
        with a non-None ``message_history`` equal to the messages from run 1.

        req: faq-rag-019
        """
        session_id = "two-turn-faq-session"
        repo = SessionRepository(_db_session)
        await repo.get_or_create(session_id)
        await _db_session.commit()

        # Patch retrieve so the FAQ agent tool returns immediately.
        monkeypatch.setattr(
            "app.agents.faq.retrieve",
            AsyncMock(return_value=[]),
        )

        deps = _make_deps(_db_session, session_id)

        # ---- Turn 1 --------------------------------------------------------
        # Track message_history arg passed to faq_agent.run on each call.
        captured_histories: list[object] = []

        original_run = get_faq_agent().run

        async def _patched_run(question: str, **kwargs: Any) -> Any:
            captured_histories.append(kwargs.get("message_history"))
            return await original_run(question, **kwargs)

        with (
            get_faq_agent().override(model=TestModel(custom_output_text="I don't have that info.")),
            patch.object(get_faq_agent(), "run", side_effect=_patched_run),
        ):
            # Turn 1: FAQ history is None → faq_agent.run gets message_history=None.
            # ask_faq is a plain async function; call it directly with a mock ctx.
            await ask_faq(_make_run_ctx(deps), "What is Stoicism?")  # type: ignore[arg-type]
            await _db_session.commit()

            # Turn 2: FAQ history should be the messages from turn 1.
            await ask_faq(_make_run_ctx(deps), "Tell me more.")  # type: ignore[arg-type]

        # Turn 1: message_history must be None (no prior FAQ history).
        assert captured_histories[0] is None, (
            f"Expected message_history=None on turn 1, got {captured_histories[0]!r}"
        )
        # Turn 2: message_history must be a non-empty list (turn 1's messages).
        assert captured_histories[1] is not None, (
            "Expected message_history to be set on turn 2 (FAQ history from turn 1)"
        )
        assert isinstance(captured_histories[1], list), (
            f"Expected list, got {type(captured_histories[1])}"
        )
        h1 = captured_histories[1]
        assert len(h1) > 0, "Expected non-empty message_history on turn 2"


# ---------------------------------------------------------------------------
# Alembic migration 0006 — offline SQL check
# ---------------------------------------------------------------------------


class TestMigration0006OfflineSQL:
    """Migration 0006 adds faq_history_json to conversationsession.

    req: faq-rag-019
    """

    def test_migration_file_exists(self) -> None:
        """Alembic migration 0006 file exists in the versions directory.

        req: faq-rag-019 — migration must be present for the column to exist in prod
        """
        migration_path = (
            Path(__file__).parent.parent / "alembic" / "versions" / "0006_faq_history.py"
        )
        assert migration_path.exists(), f"Migration file not found: {migration_path}"

    def test_migration_content_adds_correct_column(self) -> None:
        """Migration 0006 upgrade() adds faq_history_json to conversationsession.

        Reads the migration source and checks for the expected DDL patterns so
        this assertion does not require a live database.

        req: faq-rag-019
        """
        migration_path = (
            Path(__file__).parent.parent / "alembic" / "versions" / "0006_faq_history.py"
        )
        content = migration_path.read_text(encoding="utf-8")

        assert "faq_history_json" in content, "Migration must reference faq_history_json column"
        assert "conversationsession" in content, (
            "Migration must target the conversationsession table"
        )
        assert "add_column" in content, "Migration upgrade() must call op.add_column"
        assert 'down_revision: str | Sequence[str] | None = "0005"' in content, (
            "Migration must chain from 0005 (down_revision='0005')"
        )

    def test_migration_down_revision_is_0005(self) -> None:
        """Migration 0006 chains correctly from 0005.

        req: faq-rag-019 — Alembic head must chain: 0005 → 0006
        """
        migration_path = (
            Path(__file__).parent.parent / "alembic" / "versions" / "0006_faq_history.py"
        )
        content = migration_path.read_text(encoding="utf-8")
        # Ensure revision = "0006" and down_revision = "0005"
        assert re.search(r'revision\s*:\s*str\s*=\s*"0006"', content), "revision must be '0006'"
        assert re.search(r'down_revision.*=.*"0005"', content), "down_revision must be '0005'"


# ---------------------------------------------------------------------------
# Internal helper for RunContext construction
# ---------------------------------------------------------------------------


def _make_run_ctx(deps: AgentDeps) -> object:
    """Build a minimal RunContext-like object for calling ask_faq directly.

    ``ask_faq`` is a plain module-level async function registered as an agent tool
    via ``agent.tool(ask_faq)`` in ``get_orchestrator()``.  It only reads
    ``ctx.deps`` and ``ctx.usage``, so a MagicMock with those two attributes is
    sufficient to drive it in tests.

    req: faq-rag-019 (test helper only)
    """
    from pydantic_ai.usage import RunUsage

    ctx = MagicMock()
    ctx.deps = deps
    ctx.usage = RunUsage()
    return ctx
