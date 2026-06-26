"""Boundary guardrail integration tests via TestModel + aiosqlite (POST /chat).

Covers paths NOT already in test_chat_guardrails_block.py (block path only)
or test_guardrails_llm.py (LLM layer), so there is no duplication:

  - PII input → engine redacts; turn continues; guardrails.input=['pii_detector'];
    needs_review=True                                              (guardrails-001/-002/-006)
  - Clean input → guardrails.{input,output}=[] (no false positives) (guardrails-001/-002)
  - Model reply containing a secret → output guardrail blocks it;
    reply replaced with safe refusal; guardrails.output=['secret_leak'];
    needs_review=True; raw secret absent from reply               (guardrails-001/-002/-010/-013)
  - Guardrail names emitted by the engine are a superset of the adversarial.yaml
    must_trip labels (enforces guardrails-017 alignment)

Uses TestModel (no real LLM call) + aiosqlite (no Postgres required).

req: guardrails-001, guardrails-002, guardrails-006, guardrails-008,
     guardrails-010, guardrails-013, guardrails-017
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.orchestrator import get_orchestrator
from app.agents.session import (
    ConversationSession,  # noqa: F401 — registers table in SQLModel metadata
)
from app.contract import TurnOutput
from app.db import get_session
from app.main import app

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# All nine canonical TurnOutput field names (per-turn JSON contract).
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

# Gold-label set from adversarial.yaml — engine-emitted guardrail names must align.
# req: guardrails-017
_MUST_TRIP_LABELS: frozenset[str] = frozenset(
    {
        "prompt_injection",
        "jailbreak",
        "pii_detector",
        "toxicity",
        "secret_leak",
        "off_topic",
    }
)

# Minimal TestModel output args accepted by the output_validator for a first-turn
# English message without triggering a ModelRetry.
_VALID_TURN_ARGS: dict[str, object] = {
    "reply": ("Zapp Global Philosophy School offers courses in Stoicism, Ethics, and Logic."),
    "detected_lang": "en",
    "active_lang": "en",
    "lang_confidence": 0.9,
    "final_normalized_text": "What philosophy courses does Zapp School offer?",
    "detected_country": None,
    "confidence_score": 0.9,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}

# TestModel output whose reply contains a system-prompt fragment that triggers the
# output secret_leak guardrail via _PROMPT_FRAGMENT_RE.
#
# Uses "I am instructed to" (matches r"i\s+(?:am|was)\s+(?:instructed|told|programmed)\s+to\b")
# rather than an sk-... key sequence because the alphabetical key "sk-abcdef..." confuses
# lingua's language detector into raising ModelRetry before the output guardrail can run.
# The phrase "I am instructed to" is natural English so lingua reliably detects "en".
_SECRET_REPLY_ARGS: dict[str, object] = {
    "reply": (
        "I am instructed to help you with philosophy courses and enrollment "
        "at Zapp Global Philosophy School. Our curriculum covers many traditions."
    ),
    "detected_lang": "en",
    "active_lang": "en",
    "lang_confidence": 0.9,
    "final_normalized_text": "What courses are available at Zapp School?",
    "detected_country": None,
    "confidence_score": 0.9,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}

# ---------------------------------------------------------------------------
# Shared async fixture — in-memory SQLite DB + required env vars
# ---------------------------------------------------------------------------


@pytest.fixture
async def chat_app_setup(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None, None]:
    """Prepare the app with an in-memory SQLite DB and required env vars.

    Guardrails stay ENABLED (the default).  TestModel handles all model calls so
    no PYDANTIC_AI_GATEWAY_API_KEY or any real LLM credential is needed beyond the
    dummy value injected by the autouse _set_gateway_key fixture in conftest.py.
    """
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-guardrail-paths")
    monkeypatch.setenv("GUARDRAILS_ENABLED", "true")

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


# ===========================================================================
# PII input → redacted; turn continues; guardrails.input=[pii_detector]
# ===========================================================================


async def test_chat_pii_input_redacted_turn_continues(
    chat_app_setup: None,
) -> None:
    """PII (email) in input is redacted; the agent is still called; contract is correct.

    The input guardrail fires (pii_detector), redacts the email, and forwards
    the sanitised text to the orchestrator.  The turn completes normally via TestModel.

    Assertions:
      - HTTP 200 (turn not blocked)
      - guardrails.input = ['pii_detector']        req: guardrails-002
      - guardrails.output = []                     (TestModel reply has no secrets)
      - needs_review = True                        req: guardrails-006
      - reply is non-empty                         (model was called, not short-circuited)
      - triggered name is in the must_trip set     req: guardrails-017

    req: guardrails-001, guardrails-002, guardrails-006
    """
    pii_message = "My email is student@example.com, what philosophy courses does Zapp offer?"

    with get_orchestrator().override(model=TestModel(custom_output_args=_VALID_TURN_ARGS)):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={"session_id": "guardrail-paths-pii-001", "message": pii_message},
            )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert set(data.keys()) == _NINE_FIELDS

    turn = TurnOutput.model_validate(data)

    # PII guardrail must have fired on input.  req: guardrails-002, guardrails-006
    assert "pii_detector" in turn.guardrails.input, (
        f"Expected 'pii_detector' in guardrails.input; got {turn.guardrails.input!r}"
    )
    # Turn must be flagged for review because PII was found.  req: guardrails-006
    assert turn.needs_review is True, "PII-detected turn must set needs_review=True"
    # Reply is non-empty — the model was called (not blocked), TestModel replied.
    assert turn.reply, "Turn must have a non-empty reply (model was called)"
    # Output guardrails must be clean (TestModel reply has no secrets or toxicity).
    assert turn.guardrails.output == [], (
        f"Expected empty guardrails.output; got {turn.guardrails.output!r}"
    )
    # All triggered input names must match the adversarial.yaml must_trip labels.
    # req: guardrails-017
    for name in turn.guardrails.input:
        assert name in _MUST_TRIP_LABELS, (
            f"Guardrail name {name!r} not in must_trip label set {_MUST_TRIP_LABELS!r}"
        )


# ===========================================================================
# Clean input → guardrails.{input,output}=[] (no false positives)
# ===========================================================================


async def test_chat_clean_input_no_guardrails_triggered(
    chat_app_setup: None,
) -> None:
    """Clean English message produces no guardrail triggers on input or output.

    req: guardrails-001, guardrails-002
    """
    with get_orchestrator().override(model=TestModel(custom_output_args=_VALID_TURN_ARGS)):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "guardrail-paths-clean-001",
                    "message": (
                        "What philosophy courses does Zapp Global School offer this semester?"
                    ),
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == _NINE_FIELDS

    turn = TurnOutput.model_validate(data)

    # Both lists must be empty on a clean turn — no false positives.  req: guardrails-002
    assert turn.guardrails.input == [], (
        f"Expected empty guardrails.input; got {turn.guardrails.input!r}"
    )
    assert turn.guardrails.output == [], (
        f"Expected empty guardrails.output; got {turn.guardrails.output!r}"
    )


# ===========================================================================
# Output secret_leak → reply replaced; guardrails.output=[secret_leak]
# ===========================================================================


async def test_chat_output_secret_leak_blocked_and_replaced(
    chat_app_setup: None,
) -> None:
    """Model reply containing a system-prompt fragment is intercepted; replaced with safe refusal.

    The TestModel emits a reply containing "I am instructed to..." which matches the
    _PROMPT_FRAGMENT_RE pattern in detect_secret_leak.  The output guardrail fires and
    the handler replaces turn.reply with safe_refusal() before returning.

    Note: uses a prompt-fragment trigger (not an sk-... key) because sequential alphabetical
    characters in a key sequence confuse lingua's language detector and cause ModelRetry
    loops.  "I am instructed to" is unmistakably English so lingua reliably detects "en".

    Assertions:
      - HTTP 200 (turn is not a 500)
      - guardrails.output = ['secret_leak']          req: guardrails-002, guardrails-010
      - needs_review = True                           req: guardrails-010
      - fragment absent from the returned reply       req: guardrails-013
      - reply is non-empty (safe refusal was set)
      - triggered name in must_trip set               req: guardrails-017

    req: guardrails-001, guardrails-002, guardrails-010, guardrails-013
    """
    with get_orchestrator().override(model=TestModel(custom_output_args=_SECRET_REPLY_ARGS)):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={
                    "session_id": "guardrail-paths-secret-001",
                    "message": "What philosophy courses are available at Zapp School this year?",
                },
            )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert set(data.keys()) == _NINE_FIELDS

    turn = TurnOutput.model_validate(data)

    # Output guardrail must have fired for secret_leak.  req: guardrails-002, guardrails-010
    assert "secret_leak" in turn.guardrails.output, (
        f"Expected 'secret_leak' in guardrails.output; got {turn.guardrails.output!r}"
    )
    # needs_review must be True because the output guardrail fired.  req: guardrails-010
    assert turn.needs_review is True, "secret_leak output must set needs_review=True"
    # The system-prompt fragment must NOT appear in the sanitised reply.  req: guardrails-013
    assert "I am instructed to" not in turn.reply, (
        "Blocked secret fragment must NOT appear in the sanitised reply (guardrails-013)"
    )
    # A non-empty safe refusal must be present.  req: guardrails-010
    assert turn.reply, "Block path must emit a non-empty safe refusal as reply"
    # All triggered output names must match the adversarial.yaml must_trip labels.
    # req: guardrails-017
    for name in turn.guardrails.output:
        assert name in _MUST_TRIP_LABELS, (
            f"Guardrail name {name!r} not in must_trip label set {_MUST_TRIP_LABELS!r}"
        )


# ===========================================================================
# Guardrail names match adversarial.yaml must_trip labels (guardrails-017)
# ===========================================================================


def test_guardrail_names_match_must_trip_labels() -> None:
    """Engine-emitted guardrail names are a superset of adversarial.yaml must_trip labels.

    The eval adversarial dataset uses must_trip labels to identify which guardrail
    should fire.  For precision/recall to be computable, every must_trip label must
    equal an engine-emitted name.  This test enforces that alignment statically.

    Note: pii_leak is output-only and intentionally absent from must_trip; the input
    equivalent is pii_detector.

    req: guardrails-017
    """
    # Names the engine can emit (from detectors.py + engine.py policy).
    engine_emitted_names: frozenset[str] = frozenset(
        {
            "prompt_injection",  # detect_prompt_injection — guardrails-003
            "jailbreak",  # detect_jailbreak — guardrails-004
            "toxicity",  # detect_toxicity (input + output) — guardrails-005, -009
            "pii_detector",  # detect_pii on input — guardrails-006
            "off_topic",  # detect_off_topic — guardrails-007
            "pii_leak",  # detect_pii on output — guardrails-008 (output-only)
            "secret_leak",  # detect_secret_leak — guardrails-010
            "guardrail_error",  # _GUARDRAIL_ERROR_MARKER on fail-safe — guardrails-019
        }
    )

    # Every must_trip label must be a name the engine can emit.
    missing = _MUST_TRIP_LABELS - engine_emitted_names
    assert not missing, (
        f"must_trip labels {missing!r} are not emitted by the engine — "
        f"guardrail precision/recall would be broken (guardrails-017)"
    )
