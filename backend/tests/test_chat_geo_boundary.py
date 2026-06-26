"""Boundary tests for geo fusion in POST /chat — Task 6.

Verifies that the /chat handler:
  1. Resolves geo via GeoFusionService (reusing the same httpx client) AFTER input
     guardrails pass and BEFORE the orchestrator run.
  2. Passes the resolved GeoContext into AgentDeps.geo so the _reconcile_fusion
     output_validator can set detected_country on the happy path.
  3. Stamps detected_country = geo.country on the degrade path even when the
     orchestrator raises ModelHTTPError / UnexpectedModelBehavior / UsageLimitExceeded.

GeoFusionService.resolve is mocked (never raises, returns a controlled GeoContext)
so no real network calls are made.  The orchestrator is overridden with TestModel /
FunctionModel so no LLM provider key is required.  The DB is an in-memory SQLite
engine (aiosqlite + StaticPool).

req: orchestrator-and-fusion-002 — geo-IP lookup wired at the boundary
req: orchestrator-and-fusion-013 — degrade path still carries detected_country from geo
Design contract: specs/orchestrator-and-fusion/design.md §2.5
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.orchestrator import get_orchestrator
from app.agents.session import ConversationSession  # noqa: F401 — registers table in metadata
from app.contract import TurnOutput
from app.db import get_session
from app.fusion.geo import GeoContext
from app.main import app

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# Minimal valid TurnOutput payload for TestModel — detected_country intentionally set to
# null so the test confirms the _reconcile_fusion validator overwrites it with geo.country.
_VALID_TURN_ARGS: dict[str, object] = {
    "reply": "Zapp Philosophy School offers courses in Spanish, English, and Portuguese.",
    "detected_lang": "en",
    "active_lang": "en",
    "lang_confidence": 0.9,
    "final_normalized_text": "What courses do you offer?",
    "detected_country": None,
    "confidence_score": 0.9,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}

# GeoContext returned by the mocked GeoFusionService on the happy path.
_MX_GEO = GeoContext(
    country="MX",
    timezone="America/Mexico_City",
    locale="es-MX",
    source="ipapi",
    ok=True,
)

# GeoContext returned by the mocked GeoFusionService on the degrade path.
_BR_GEO = GeoContext(
    country="BR",
    timezone="America/Sao_Paulo",
    locale="pt-BR",
    source="ipapi",
    ok=True,
)


# ---------------------------------------------------------------------------
# Shared async fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def geo_app_setup(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None, None]:
    """In-memory SQLite engine + required env vars for geo boundary tests.

    Pattern mirrors test_chat_degrade.py — one fixture, multiple test methods.
    """
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-geo")

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
# Helpers — mock GeoFusionService
# ---------------------------------------------------------------------------


def _make_geo_service_mock(geo_context: GeoContext) -> MagicMock:
    """Return a mock for the GeoFusionService class whose instance.resolve returns geo_context."""
    mock_instance = MagicMock()
    mock_instance.resolve = AsyncMock(return_value=geo_context)
    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls


def _model_raising_http_error() -> FunctionModel:
    def _raise(messages: object, agent_info: object) -> object:
        raise ModelHTTPError(503, "test-model", body={"error": "Service Unavailable"})

    return FunctionModel(_raise)  # type: ignore[arg-type]


def _model_raising_unexpected_behavior() -> FunctionModel:
    def _raise(messages: object, agent_info: object) -> object:
        raise UnexpectedModelBehavior("model returned garbage")

    return FunctionModel(_raise)  # type: ignore[arg-type]


def _model_raising_usage_limit() -> FunctionModel:
    def _raise(messages: object, agent_info: object) -> object:
        raise UsageLimitExceeded("request_limit=1 exceeded")

    return FunctionModel(_raise)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChatGeoBoundary:
    """Verify that GeoFusionService.resolve is wired at the boundary and that
    detected_country propagates correctly on both the happy and degrade paths."""

    # ------------------------------------------------------------------
    # Happy path — resolved geo carried into deps → _reconcile_fusion sets detected_country
    # ------------------------------------------------------------------

    async def test_happy_path_detected_country_from_geo(
        self,
        geo_app_setup: None,
    ) -> None:
        """Happy path: resolved GeoContext.country (MX) propagates to detected_country.

        GeoFusionService.resolve is mocked to return MX geo.  The orchestrator runs via
        TestModel; the _reconcile_fusion output_validator sets detected_country from
        deps.geo.country.  The response must have detected_country = "MX".

        req: orchestrator-and-fusion-002 — geo-IP wired at boundary
        req: orchestrator-and-fusion-001 — detected_country code-set from geo signal
        """
        mock_geo_cls = _make_geo_service_mock(_MX_GEO)

        with (
            patch("app.api.chat.GeoFusionService", mock_geo_cls),
            get_orchestrator().override(model=TestModel(custom_output_args=_VALID_TURN_ARGS)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/chat",
                    json={
                        "session_id": "geo-happy-mx-001",
                        "message": "What philosophy courses do you offer?",
                    },
                )

        assert response.status_code == 200, (
            f"Expected 200 on happy path, got {response.status_code}: {response.text}"
        )
        turn = TurnOutput.model_validate(response.json())

        # _reconcile_fusion sets detected_country = deps.geo.country = "MX"
        # req: orchestrator-and-fusion-001
        assert str(turn.detected_country) == "MX", (
            f"Expected detected_country='MX' from resolved geo, got {turn.detected_country!r}"
        )

        # GeoFusionService was instantiated once and resolve was called once.
        # req: orchestrator-and-fusion-002
        mock_geo_cls.assert_called_once()
        mock_geo_cls.return_value.resolve.assert_awaited_once()

    # ------------------------------------------------------------------
    # Degrade paths — geo.country stamped AFTER degraded_turn() call
    # ------------------------------------------------------------------

    async def test_degrade_model_http_error_carries_detected_country(
        self,
        geo_app_setup: None,
    ) -> None:
        """Degrade path (ModelHTTPError): detected_country still set from resolved geo.

        GeoFusionService.resolve returns BR geo before the orchestrator run.  The model
        raises ModelHTTPError; the boundary degrades gracefully and stamps
        turn.detected_country = geo.country = "BR" after calling degraded_turn().

        req: orchestrator-and-fusion-013 — degrade path carries detected_country
        """
        mock_geo_cls = _make_geo_service_mock(_BR_GEO)

        with (
            patch("app.api.chat.GeoFusionService", mock_geo_cls),
            get_orchestrator().override(model=_model_raising_http_error()),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/chat",
                    json={
                        "session_id": "geo-degrade-http-br-001",
                        "message": "Olá, quais cursos vocês oferecem?",
                    },
                )

        assert response.status_code == 200, (
            f"Expected 200 on degrade path, got {response.status_code}: {response.text}"
        )
        turn = TurnOutput.model_validate(response.json())

        assert turn.needs_review is True, "Degrade path must set needs_review=True"
        # req: orchestrator-and-fusion-013 — degrade path still reports detected_country
        assert str(turn.detected_country) == "BR", (
            f"Expected detected_country='BR' on degrade path, got {turn.detected_country!r}"
        )

    async def test_degrade_unexpected_behavior_carries_detected_country(
        self,
        geo_app_setup: None,
    ) -> None:
        """Degrade path (UnexpectedModelBehavior): detected_country stamped from geo.

        req: orchestrator-and-fusion-013
        """
        mock_geo_cls = _make_geo_service_mock(_MX_GEO)

        with (
            patch("app.api.chat.GeoFusionService", mock_geo_cls),
            get_orchestrator().override(model=_model_raising_unexpected_behavior()),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/chat",
                    json={
                        "session_id": "geo-degrade-unexpected-mx-001",
                        "message": "¿Cuáles son los cursos?",
                    },
                )

        assert response.status_code == 200
        turn = TurnOutput.model_validate(response.json())
        assert turn.needs_review is True
        assert str(turn.detected_country) == "MX", (
            f"Expected detected_country='MX' on UnexpectedModelBehavior degrade, "
            f"got {turn.detected_country!r}"
        )

    async def test_degrade_usage_limit_carries_detected_country(
        self,
        geo_app_setup: None,
    ) -> None:
        """Degrade path (UsageLimitExceeded): detected_country stamped from geo.

        req: orchestrator-and-fusion-013
        """
        mock_geo_cls = _make_geo_service_mock(_BR_GEO)

        with (
            patch("app.api.chat.GeoFusionService", mock_geo_cls),
            get_orchestrator().override(model=_model_raising_usage_limit()),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/chat",
                    json={
                        "session_id": "geo-degrade-usage-br-001",
                        "message": "Hello, I want to enroll.",
                    },
                )

        assert response.status_code == 200
        turn = TurnOutput.model_validate(response.json())
        assert turn.needs_review is True
        assert str(turn.detected_country) == "BR", (
            f"Expected detected_country='BR' on UsageLimitExceeded degrade, "
            f"got {turn.detected_country!r}"
        )

    async def test_degrade_geo_error_detected_country_is_null(
        self,
        geo_app_setup: None,
    ) -> None:
        """Degrade path + geo-error: detected_country=None (null in JSON) is correct.

        When GeoFusionService.resolve returns source="error" (e.g., network timeout),
        geo.country is None.  The degrade path sets turn.detected_country = geo.country
        = None, which is the correct safe value.

        req: orchestrator-and-fusion-009, orchestrator-and-fusion-013
        """
        error_geo = GeoContext(source="error", ok=False)  # country=None
        mock_geo_cls = _make_geo_service_mock(error_geo)

        with (
            patch("app.api.chat.GeoFusionService", mock_geo_cls),
            get_orchestrator().override(model=_model_raising_http_error()),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/chat",
                    json={
                        "session_id": "geo-degrade-error-null-001",
                        "message": "What courses are there?",
                    },
                )

        assert response.status_code == 200
        turn = TurnOutput.model_validate(response.json())
        assert turn.needs_review is True
        # geo.country is None on error → detected_country is None (null in JSON)
        assert turn.detected_country is None, (
            f"Expected detected_country=None on geo-error degrade, got {turn.detected_country!r}"
        )
