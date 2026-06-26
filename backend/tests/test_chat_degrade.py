"""Integration test for the POST /chat degrade path.

Verifies that when the orchestrator agent raises ``ModelHTTPError``,
``UnexpectedModelBehavior``, or ``UsageLimitExceeded``, the ``/chat`` boundary:
  - returns HTTP 200 (never a 500)
  - returns a valid ``TurnOutput`` with ``needs_review=True``
  - sets ``active_lang`` to the session's resolved language (not an empty string)

The agent is overridden via ``get_orchestrator().override(model=FunctionModel(fn))``
where the function raises the target exception, exercising the real FastAPI except
branch in ``app/api/chat.py``.

An in-memory SQLite engine (aiosqlite + StaticPool) replaces Postgres so no real
database is required.

req: multilingual-001 — degrade path still emits all nine TurnOutput fields
req: multilingual-004 — active_lang is set (first-turn lock resolves before the agent runs)
Design contract: specs/multilingual/design.md §2.6 (degraded path sequence)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.function import FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.orchestrator import get_orchestrator
from app.agents.session import ConversationSession  # noqa: F401 — registers table in metadata
from app.contract import TurnOutput
from app.db import get_session
from app.main import app

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# The nine canonical TurnOutput field names (per-turn JSON contract).
_NINE_FIELDS: frozenset[str] = frozenset(
    {
        "reply",
        "detected_lang",
        "active_lang",
        "lang_confidence",
        "final_normalized_text",
        "detected_country",
        "confidence_score",
        "needs_review",
        "guardrails",
    }
)


# ---------------------------------------------------------------------------
# Shared async fixture — in-memory SQLite + env var setup
# ---------------------------------------------------------------------------


@pytest.fixture
async def degrade_app_setup(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None, None]:
    """Prepare the app with an in-memory SQLite DB and required env vars.

    Mirrors the pattern used in test_chat_multilingual.py so the two test
    modules can coexist without colliding on the DB state.
    """
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-degrade")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-ant-key-degrade")

    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override

    yield

    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


# ---------------------------------------------------------------------------
# FunctionModel helpers — one per exception type
# ---------------------------------------------------------------------------


def _model_raising_http_error() -> FunctionModel:
    """Return a FunctionModel whose request() always raises ModelHTTPError(503)."""

    def _raise_http(messages: object, agent_info: object) -> object:
        raise ModelHTTPError(503, "test-model", body={"error": "Service Unavailable"})

    return FunctionModel(_raise_http)


def _model_raising_unexpected_behavior() -> FunctionModel:
    """Return a FunctionModel whose request() always raises UnexpectedModelBehavior."""

    def _raise_unexpected(messages: object, agent_info: object) -> object:
        raise UnexpectedModelBehavior("Unexpected output: model returned garbage")

    return FunctionModel(_raise_unexpected)


def _model_raising_usage_limit() -> FunctionModel:
    """Return a FunctionModel whose request() always raises UsageLimitExceeded."""

    def _raise_usage(messages: object, agent_info: object) -> object:
        raise UsageLimitExceeded("request_limit=1 exceeded")

    return FunctionModel(_raise_usage)


# ---------------------------------------------------------------------------
# Degrade path — ModelHTTPError
# ---------------------------------------------------------------------------


async def test_chat_degrade_model_http_error_returns_200_needs_review(
    degrade_app_setup: None,
) -> None:
    """ModelHTTPError in the orchestrator → HTTP 200, needs_review=True, not a 500.

    req: multilingual-001 — all nine TurnOutput fields present on the degrade path
    """
    with get_orchestrator().override(model=_model_raising_http_error()):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "degrade-http-error-001",
                    "message": "Hello, I need help with the courses.",
                },
            )

    # Must be 200, not 500.  req: multilingual-001 (degrade path)
    assert response.status_code == 200, (
        f"Expected 200 on degrade path, got {response.status_code}: {response.text}"
    )

    data = response.json()

    # All nine contract fields must be present.  req: multilingual-001
    assert set(data.keys()) == _NINE_FIELDS, (
        f"Missing/extra fields: {set(data.keys()).symmetric_difference(_NINE_FIELDS)}"
    )

    # Deserialises without ValidationError.
    turn = TurnOutput.model_validate(data)

    # Degrade path must signal that human review is warranted.
    assert turn.needs_review is True, "Degrade path must set needs_review=True"

    # active_lang must be one of the supported codes — degraded_turn() preserves the
    # resolve_active_lang() decision even when the model call fails.
    # req: multilingual-003
    assert turn.active_lang in ("es", "en", "pt"), (
        f"active_lang {turn.active_lang!r} not in supported set"
    )

    # reply must be a non-empty safe message in active_lang.  req: multilingual-001
    assert turn.reply, "Degrade path reply must not be empty"

    # lang_confidence should be 0 on the degrade path (degraded_turn() sets it to 0.0).
    assert turn.lang_confidence == 0.0


# ---------------------------------------------------------------------------
# Degrade path — UnexpectedModelBehavior
# ---------------------------------------------------------------------------


async def test_chat_degrade_unexpected_behavior_returns_200_needs_review(
    degrade_app_setup: None,
) -> None:
    """UnexpectedModelBehavior in the orchestrator → HTTP 200, needs_review=True.

    req: multilingual-001 — degrade contract holds for all three caught exception types
    """
    with get_orchestrator().override(model=_model_raising_unexpected_behavior()):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "degrade-unexpected-001",
                    "message": "¿Cuáles son los cursos disponibles?",
                },
            )

    assert response.status_code == 200
    turn = TurnOutput.model_validate(response.json())
    assert turn.needs_review is True
    assert turn.active_lang in ("es", "en", "pt")


# ---------------------------------------------------------------------------
# Degrade path — UsageLimitExceeded
# ---------------------------------------------------------------------------


async def test_chat_degrade_usage_limit_exceeded_returns_200_needs_review(
    degrade_app_setup: None,
) -> None:
    """UsageLimitExceeded → HTTP 200, needs_review=True, all nine fields.

    req: multilingual-001 — degrade contract holds for all three caught exception types
    """
    with get_orchestrator().override(model=_model_raising_usage_limit()):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "degrade-usage-limit-001",
                    "message": "Olá, quero saber sobre os cursos de filosofia.",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == _NINE_FIELDS

    turn = TurnOutput.model_validate(data)
    assert turn.needs_review is True
    assert turn.active_lang in ("es", "en", "pt")
    assert turn.reply  # safe fallback reply must be present


# ---------------------------------------------------------------------------
# Degrade path — active_lang is resolved before the agent runs (first-turn lock)
# ---------------------------------------------------------------------------


async def test_chat_degrade_active_lang_matches_detected_language(
    degrade_app_setup: None,
) -> None:
    """On the degrade path, active_lang reflects the pre-agent resolve_active_lang decision.

    A Spanish message → resolve_active_lang locks to 'es' → degraded_turn('es') → reply
    is in Spanish even though the model never ran.

    req: multilingual-004 — first-turn lock decision is preserved on the degrade path
    """
    with get_orchestrator().override(model=_model_raising_http_error()):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "degrade-active-lang-es-001",
                    "message": (
                        "Hola, me gustaría conocer más sobre los cursos de filosofía "
                        "disponibles en Zapp."
                    ),
                },
            )

    assert response.status_code == 200
    turn = TurnOutput.model_validate(response.json())
    assert turn.needs_review is True
    # The Spanish message should lock to 'es'; the degraded reply should be in Spanish.
    assert turn.active_lang == "es", (
        f"Expected active_lang='es' for Spanish input on degrade path, got {turn.active_lang!r}"
    )
