"""Tests for the POST /chat endpoint — basic contract.

The original scaffold stub (platform-scaffold-009, -010) has been replaced by the
real multilingual handler in Task 9.  These tests verify that the core contract
(HTTP 200 + all nine TurnOutput fields) is preserved after the replacement.

For the full boundary integration test, see test_chat_multilingual.py.

Requirements:
- multilingual-001 (formerly platform-scaffold-009): POST /chat returns a valid
  TurnOutput with all nine contract fields populated on every turn.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.orchestrator import get_orchestrator
from app.agents.session import ConversationSession  # noqa: F401 — registers the table in metadata
from app.contract import TurnOutput
from app.db import get_session
from app.main import app

# The nine canonical TurnOutput field names (non-negotiable per the per-turn JSON contract).
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

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# Minimal valid TurnOutput payload — used to prime TestModel so the orchestrator
# produces a type-correct output without a real LLM call.
_VALID_TURN_ARGS: dict[str, object] = {
    "reply": "Hello! Zapp Philosophy School offers courses in ES, EN, and PT.",
    "detected_lang": "en",
    "active_lang": "en",
    "lang_confidence": 0.9,
    "final_normalized_text": "Hello, what courses are there?",
    "detected_country": None,
    "confidence_score": 0.9,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}


async def test_chat_returns_200_with_all_nine_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /chat returns 200 and a valid TurnOutput with all nine contract fields.

    Uses an in-memory SQLite engine (aiosqlite) and TestModel so neither Postgres
    nor a real LLM provider key is required.

    # multilingual-001 / platform-scaffold-009
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

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session

    try:
        with get_orchestrator().override(model=TestModel(custom_output_args=_VALID_TURN_ARGS)):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/chat",
                    json={
                        "session_id": "scaffold-contract-test-001",
                        "message": "Hello, what courses are there?",
                    },
                )
    finally:
        app.dependency_overrides.pop(get_session, None)
        await engine.dispose()

    assert response.status_code == 200
    data = response.json()
    # Exactly the nine contract fields must be present. multilingual-001
    assert set(data.keys()) == _NINE_FIELDS
    # Body must deserialize without ValidationError.
    output = TurnOutput.model_validate(data)
    assert output is not None
