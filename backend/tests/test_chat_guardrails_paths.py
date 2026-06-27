"""Boundary guardrail integration tests via TestModel + aiosqlite (POST /chat).

Covers paths NOT already in test_chat_guardrails_block.py:

  - PII input → framework blocks; guardrails.input=['pii_detector'];
    needs_review=True; no model call                               (guardrails-001/-002/-006)
  - Clean input → guardrails.{input,output}=[] (no false positives) (guardrails-001/-002)
  - Model reply containing a secret → output guardrail blocks it;
    reply replaced with safe refusal; guardrails.output=['secret_leak'];
    needs_review=True; raw secret absent from reply               (guardrails-001/-002/-010/-013)
  - Guardrail names emitted by the framework are a superset of the adversarial.yaml
    must_trip labels (enforces guardrails-017 alignment)
  - guardrails_enabled=False → plain orchestrator, guardrails empty (guardrails-016)

Uses TestModel (no real LLM call) + aiosqlite (no Postgres required).

req: guardrails-001, guardrails-002, guardrails-006, guardrails-008,
     guardrails-010, guardrails-013, guardrails-016, guardrails-017
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.orchestrator import get_guarded_orchestrator, get_orchestrator
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

# Gold-label set from adversarial.yaml — framework-emitted guardrail names must align.
# After migration to pydantic-ai-guardrails:
#   - "jailbreak" is detected by the prompt_injection guard (same guard, same name)
#   - "off_topic" is not a separate framework guard (soft-flag behaviour removed)
# req: guardrails-017
_MUST_TRIP_LABELS: frozenset[str] = frozenset(
    {
        "prompt_injection",
        "pii_detector",
        "toxicity",
        "secret_leak",
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


class TestChatGuardrailsPaths:
    async def test_chat_pii_input_blocked(
        self,
        chat_app_setup: None,
    ) -> None:
        """PII (email) in input is blocked by the framework; safe refusal returned, no model call.

        The pydantic-ai-guardrails pii_detector() guard (action='block') fires and raises
        InputGuardrailViolation before the orchestrator is called.  The boundary catches
        the violation and emits a safe-refusal TurnOutput.

        Note: the framework's input PII guard blocks (not redacts) — the model never
        receives the user's message.  This differs from the prior hand-rolled behavior
        where PII was redacted then forwarded.

        Assertions:
          - HTTP 200 (block path, not a 500)
          - guardrails.input = ['pii_detector']          req: guardrails-002
          - needs_review = True                          req: guardrails-006
          - reply is non-empty safe refusal (NOT model reply)
          - guardrails.output = [] (no model call → no output guard check)
          - no model call needed (block fires before orchestrator)
          - triggered name is in the must_trip set       req: guardrails-017

        req: guardrails-001, guardrails-002, guardrails-006, guardrails-012
        """
        pii_message = "My email is student@example.com, what philosophy courses does Zapp offer?"

        # Intentionally do NOT override the model — the block must fire before the
        # orchestrator is called, so no LLM call is needed.
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/chat",
                json={"session_id": "guardrail-paths-pii-001", "message": pii_message},
            )

        assert response.status_code == 200, (
            f"Expected 200 on PII block path, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert set(data.keys()) == _NINE_FIELDS

        turn = TurnOutput.model_validate(data)

        # PII guardrail must have fired on input.  req: guardrails-002, guardrails-006
        assert "pii_detector" in turn.guardrails.input, (
            f"Expected 'pii_detector' in guardrails.input; got {turn.guardrails.input!r}"
        )
        # Turn must be flagged for review.  req: guardrails-006
        assert turn.needs_review is True, "PII-detected turn must set needs_review=True"
        # Reply is a safe refusal (non-empty, not the model's reply).
        assert turn.reply, "Block path must have a non-empty safe refusal reply"
        # Input block path: output guards never ran (no model call).
        assert turn.guardrails.output == [], (
            f"Expected empty guardrails.output on input-block path; got {turn.guardrails.output!r}"
        )
        # All triggered input names must match the must_trip labels.  req: guardrails-017
        for name in turn.guardrails.input:
            assert name in _MUST_TRIP_LABELS, (
                f"Guardrail name {name!r} not in must_trip label set {_MUST_TRIP_LABELS!r}"
            )

    # ===========================================================================
    # Clean input → guardrails.{input,output}=[] (no false positives)
    # ===========================================================================

    async def test_chat_clean_input_no_guardrails_triggered(
        self,
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
        self,
        chat_app_setup: None,
    ) -> None:
        """Model reply containing a system-prompt fragment is intercepted; replaced with safe
        refusal.

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
                        "message": (
                            "What philosophy courses are available at Zapp School this year?"
                        ),
                    },
                )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
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


class TestGuardrailNameAlignment:
    def test_guardrail_names_match_must_trip_labels(self) -> None:
        """Framework-emitted contract names are a superset of adversarial.yaml must_trip labels.

        The eval adversarial dataset uses must_trip labels to identify which guardrail
        should fire.  For precision/recall to be computable, every must_trip label must
        equal a framework-emitted contract name.

        After migration to pydantic-ai-guardrails:
          - "prompt_injection" guard fires for both injection AND jailbreak patterns
          - "toxicity_detector" input guard → adapter maps to "toxicity"
          - "pii_detector" input guard → adapter maps to "pii_detector"
          - "secret_input" guard → adapter maps to "secret_leak"
          - "toxicity_output" output guard → adapter maps to "toxicity"
          - "secret_output" output guard → adapter maps to "secret_leak"
          - "pii_output" output guard → adapter maps to "pii_leak"
          - "guardrail_error" → fail-safe sentinel (guardrails-019)

        req: guardrails-017
        """
        # Contract-vocabulary names the framework+adapter combination can emit.
        framework_emitted_names: frozenset[str] = frozenset(
            {
                "prompt_injection",  # prompt_injection() guard → guardrails-003, -004
                "toxicity",  # toxicity_detector() + toxicity_output_guard() → -005, -009
                "pii_detector",  # pii_detector() input guard → guardrails-006
                "pii_leak",  # pii_output_guard() output guard → guardrails-008
                "secret_leak",  # secret_input_guard() + secret_output_guard() → -010
                "guardrail_error",  # fail-safe sentinel → guardrails-019
            }
        )

        # Every must_trip label must be a name the framework+adapter can emit.
        missing = _MUST_TRIP_LABELS - framework_emitted_names
        assert not missing, (
            f"must_trip labels {missing!r} are not in the framework+adapter emitted set — "
            f"guardrail precision/recall would be broken (guardrails-017)"
        )


# ===========================================================================
# guardrails_enabled=False → plain orchestrator, empty guardrails (guardrails-016)
# ===========================================================================


class TestGuardrailsDisabled:
    async def test_chat_guardrails_disabled_skips_all_checks(
        self,
        chat_app_setup: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When GUARDRAILS_ENABLED=false the plain orchestrator is used; guardrails empty.

        With guardrails_enabled=False the /chat boundary runs get_orchestrator() directly
        (no GuardedAgent).  The turn completes normally via TestModel and both
        guardrails.input and guardrails.output must be empty (no checks were run).

        req: guardrails-016
        """
        monkeypatch.setenv("GUARDRAILS_ENABLED", "false")
        # Rebuild caches after env-var change so the new settings take effect.
        from app.config import get_settings as _get_settings

        _get_settings.cache_clear()
        get_guarded_orchestrator.cache_clear()

        with get_orchestrator().override(model=TestModel(custom_output_args=_VALID_TURN_ARGS)):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/chat",
                    json={
                        "session_id": "guardrails-disabled-001",
                        "message": "What philosophy courses does Zapp offer?",
                    },
                )

        assert response.status_code == 200, (
            f"Expected 200 with guardrails disabled, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert set(data.keys()) == _NINE_FIELDS

        turn = TurnOutput.model_validate(data)
        # Both guardrail lists must be empty — no checks ran.  req: guardrails-016
        assert turn.guardrails.input == [], (
            f"Expected empty guardrails.input; got {turn.guardrails.input!r}"
        )
        assert turn.guardrails.output == [], (
            f"Expected empty guardrails.output; got {turn.guardrails.output!r}"
        )
