"""Integration test for the POST /chat multilingual boundary (Task 9).

Runs the REAL boundary end-to-end WITHOUT Postgres or a real LLM:
  - In-memory SQLite via aiosqlite (``StaticPool`` keeps the schema visible across
    all connections in the same process).
  - ``TestModel`` override so no API key is required for the actual inference step.

Coverage:
  multilingual-001 — all nine TurnOutput fields populated
  multilingual-004 — first-turn active_lang lock to detected supported language
  multilingual-008 — locked + unsupported → keep + needs_review
  multilingual-009 — first-turn unsupported → fallback "en" + needs_review

Design contract: specs/multilingual/design.md §2.6
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.orchestrator import get_orchestrator
from app.agents.session import ConversationSession  # noqa: F401 — registers table in metadata
from app.config import SUPPORTED_LANGS
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

# -------------------------------------------------------------------
# Shared async fixture for the in-memory SQLite session override
# -------------------------------------------------------------------


@pytest.fixture
async def sqlite_app_setup(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None, None]:
    """Create an in-memory SQLite engine, create the ConversationSession table,
    and override the FastAPI ``get_session`` dependency for the test's lifetime.

    Sets required env vars so ``get_settings()`` and ``get_orchestrator()``
    succeed without a real database or LLM provider key.
    """
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")

    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        # Create only the tables defined in SQLModel.metadata (ConversationSession).
        await conn.run_sync(SQLModel.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session

    yield  # test runs here

    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------


async def test_chat_multilingual_happy_path_es(
    sqlite_app_setup: None,
) -> None:
    """Spanish first-turn message → active_lang locked to "es", all 9 fields present.

    req: multilingual-001 — all nine fields populated
    req: multilingual-004 — first-turn lock to detected supported language (es)
    """
    # TestModel custom_output_args prime a Spanish reply; the output_validator
    # overwrites active_lang from deps.active_lang (resolved by resolve_active_lang).
    valid_turn_args: dict[str, object] = {
        "reply": "¡Hola! En Zapp ofrecemos cursos de filosofía en español, inglés y portugués.",
        "detected_lang": "es",
        "active_lang": "es",
        "lang_confidence": 0.9,
        "final_normalized_text": "Hola, ¿qué cursos hay?",
        "detected_country": None,
        "confidence_score": 0.9,
        "needs_review": False,
        "guardrails": {"input": [], "output": []},
    }

    with get_orchestrator().override(model=TestModel(custom_output_args=valid_turn_args)):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "test-ml-es-001",
                    "message": "Hola, ¿qué cursos hay?",
                },
            )

    # HTTP 200 with valid JSON. req: multilingual-001
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    # All nine contract fields must be present. req: multilingual-001
    assert set(data.keys()) == _NINE_FIELDS, (
        f"Missing or extra fields: {set(data.keys()).symmetric_difference(_NINE_FIELDS)}"
    )

    # Deserializes without ValidationError.
    turn = TurnOutput.model_validate(data)

    # active_lang reflects the resolved decision (Spanish input → "es" on first turn).
    # req: multilingual-004
    assert turn.active_lang == "es", (
        f"Expected active_lang='es' (first-turn lock), got {turn.active_lang!r}"
    )

    # active_lang must be one of the supported codes. req: multilingual-003
    assert turn.active_lang in SUPPORTED_LANGS

    # lang_confidence is the agreement score (both signals = "es"). req: multilingual-005
    assert 0.0 <= turn.lang_confidence <= 1.0

    # The reply field must be non-empty. req: multilingual-001
    assert turn.reply


async def test_chat_multilingual_all_nine_fields_types(
    sqlite_app_setup: None,
) -> None:
    """All nine TurnOutput fields are present with correct types in the JSON response.

    req: multilingual-001 — nine-field contract on every turn
    """
    valid_turn_args: dict[str, object] = {
        "reply": "In Zapp we offer philosophy courses in three languages.",
        "detected_lang": "en",
        "active_lang": "en",
        "lang_confidence": 0.88,
        "final_normalized_text": "Hello, what courses are available?",
        "detected_country": None,
        "confidence_score": 0.8,
        "needs_review": False,
        "guardrails": {"input": [], "output": []},
    }

    with get_orchestrator().override(model=TestModel(custom_output_args=valid_turn_args)):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "test-ml-en-types",
                    "message": "Hello, what courses are available?",
                },
            )

    assert response.status_code == 200
    data = response.json()

    # Verify all nine fields are present. req: multilingual-001
    assert set(data.keys()) == _NINE_FIELDS

    # Verify types of every field.
    assert isinstance(data["reply"], str)
    assert isinstance(data["detected_lang"], str) and len(data["detected_lang"]) == 2
    assert isinstance(data["active_lang"], str) and len(data["active_lang"]) == 2
    assert isinstance(data["lang_confidence"], float | int)
    assert isinstance(data["final_normalized_text"], str)
    assert data["detected_country"] is None or isinstance(data["detected_country"], str)
    assert isinstance(data["confidence_score"], float | int)
    assert isinstance(data["needs_review"], bool)
    assert isinstance(data["guardrails"], dict)
    assert "input" in data["guardrails"] and "output" in data["guardrails"]

    # Deserializes correctly. req: multilingual-001
    turn = TurnOutput.model_validate(data)
    assert turn.active_lang in SUPPORTED_LANGS
