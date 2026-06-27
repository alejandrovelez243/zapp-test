"""Tests for switch_language + end_session orchestrator tools.

Verifies:
  1. switch_language tool updates deps.active_lang + deps.lang_switch_requested
     when called with a valid supported language. (req: multilingual-015)
  2. switch_language rejects unsupported languages — no state change.
  3. switch_language is a no-op when target_lang == current active_lang.
  4. end_session tool sets deps.session_ended = True. (req: evaluation-015)
  5. end_session returns a confirmation message.
  6. is_goodbye is NOT exported from app.eval.runtime (no dangling refs after removal).
  7. FunctionModel-based integration: model calling switch_language updates
     deps.active_lang and output.active_lang via the output_validator.
  8. FunctionModel-based integration: model calling end_session sets
     deps.session_ended = True for the boundary to read.

req: multilingual-015, evaluation-015
Design contract: specs/multilingual/design.md §2.4, specs/evaluation/design.md §3.3
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import end_session, get_orchestrator, switch_language
from app.deps import AgentDeps
from app.lang.detector import DetectionResult
from app.lang.state import ActiveLangDecision

# ---------------------------------------------------------------------------
# Module-level env fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set DATABASE_URL and ADMIN_TOKEN so get_settings() succeeds."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")


# ---------------------------------------------------------------------------
# Minimal mock RunContext — duck-typed for tool unit tests.
# The tool functions only access ctx.deps, so a simple dataclass suffices.
# ---------------------------------------------------------------------------


@dataclass
class _MockCtx:
    """Minimal stand-in for RunContext[AgentDeps] used in direct tool-function calls.

    PydanticAI does not enforce RunContext types at runtime; the tools only read
    ``ctx.deps``.  Using a dataclass avoids importing private pydantic-ai internals.
    """

    deps: AgentDeps


def _make_deps(active_lang: str = "en") -> AgentDeps:
    """Return minimal AgentDeps for unit tests (mocked DB + HTTP, reliable EN detection)."""
    return AgentDeps(
        session=AsyncMock(spec=AsyncSession),
        http=AsyncMock(spec=httpx.AsyncClient),
        session_id="tool-test-session",
        request_ip="127.0.0.1",
        active_lang=active_lang,
        detection=DetectionResult(lang=active_lang, confidence=0.95, is_reliable=True),
        lang_decision=ActiveLangDecision(
            active_lang=active_lang,
            first_turn=True,
            locked=False,
            fallback_used=False,
        ),
    )


# ---------------------------------------------------------------------------
# Valid TurnOutput args used by FunctionModel tests
# ---------------------------------------------------------------------------

_VALID_TURN_EN: dict[str, Any] = {
    "reply": "Goodbye! Feel free to return whenever you have more questions.",
    "detected_lang": "en",
    "active_lang": "en",
    "lang_confidence": 0.95,
    "final_normalized_text": "Goodbye, that is all I needed.",
    "detected_country": None,
    "confidence_score": 0.9,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}

_VALID_TURN_ES: dict[str, Any] = {
    "reply": "¡Claro! Ahora continuaremos en español.",
    "detected_lang": "en",
    "active_lang": "es",
    "lang_confidence": 0.9,
    "final_normalized_text": "Please switch to Spanish.",
    "detected_country": None,
    "confidence_score": 0.85,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}


# ---------------------------------------------------------------------------
# FunctionModel factories
# ---------------------------------------------------------------------------


def _make_end_session_model(output_args: dict[str, Any]) -> FunctionModel:
    """Return a FunctionModel that calls end_session then returns a structured output.

    Simulates a model that recognises a goodbye intent and calls the end_session tool
    (with reason='user_goodbye') before returning its final TurnOutput.
    """
    call_count = [0]

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            # First call → make the end_session tool call.
            # ToolCallPart constructor: tool_name, args (dict or JSON str), tool_call_id.
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="end_session",
                        args={"reason": "user_goodbye"},
                        tool_call_id="end_session_call_1",
                    )
                ]
            )
        # Second call (after tool return) → produce the final structured output.
        output_tool = info.output_tools[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=output_tool.name,
                    args=output_args,
                    tool_call_id="output_call_1",
                )
            ]
        )

    return FunctionModel(model_fn)


def _make_switch_language_model(target_lang: str, output_args: dict[str, Any]) -> FunctionModel:
    """Return a FunctionModel that calls switch_language(target_lang) then returns output.

    Simulates a model that recognises an explicit language-switch request and calls the
    switch_language tool with the specified target language.
    """
    call_count = [0]

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            # First call → make the switch_language tool call.
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="switch_language",
                        args={"target_lang": target_lang},
                        tool_call_id="switch_call_1",
                    )
                ]
            )
        # Second call (after tool return) → produce the final structured output.
        output_tool = info.output_tools[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=output_tool.name,
                    args=output_args,
                    tool_call_id="output_call_1",
                )
            ]
        )

    return FunctionModel(model_fn)


# ===========================================================================
# Unit tests — switch_language tool function (direct call, mock ctx)
# req: multilingual-015
# ===========================================================================


class TestSwitchLanguageTool:
    """Direct unit tests for the switch_language tool function.

    Calls the function with a duck-typed mock context so no agent run is needed.
    """

    async def test_switch_to_supported_lang_updates_active_lang(self) -> None:
        """switch_language('es') on an EN session → deps.active_lang becomes 'es'.

        req: multilingual-015 — tool updates deps.active_lang in-place
        """
        deps = _make_deps(active_lang="en")
        ctx = _MockCtx(deps=deps)

        result = await switch_language(ctx, "es")  # type: ignore[arg-type]

        assert deps.active_lang == "es", (
            f"Expected deps.active_lang='es' after switch; got {deps.active_lang!r}"
        )
        assert "Spanish" in result or "es" in result, (
            f"Expected confirmation mentioning 'Spanish' or 'es'; got {result!r}"
        )

    async def test_switch_to_supported_lang_sets_lang_switch_requested(self) -> None:
        """switch_language('pt') sets deps.lang_switch_requested for boundary persistence.

        req: multilingual-015 — lang_switch_requested signals _run_orchestrator_turn
        """
        deps = _make_deps(active_lang="en")
        ctx = _MockCtx(deps=deps)

        await switch_language(ctx, "pt")  # type: ignore[arg-type]

        assert deps.lang_switch_requested == "pt", (
            f"Expected deps.lang_switch_requested='pt'; got {deps.lang_switch_requested!r}"
        )

    async def test_switch_to_unsupported_lang_leaves_deps_unchanged(self) -> None:
        """switch_language('fr') → deps unchanged; tool returns error message.

        req: multilingual-015 — only supported langs (es/en/pt) are accepted
        """
        deps = _make_deps(active_lang="en")
        ctx = _MockCtx(deps=deps)

        result = await switch_language(ctx, "fr")  # type: ignore[arg-type]

        assert deps.active_lang == "en", (
            f"deps.active_lang must not change for unsupported lang; got {deps.active_lang!r}"
        )
        assert deps.lang_switch_requested is None, (
            "deps.lang_switch_requested must remain None for unsupported lang"
        )
        assert "not supported" in result.lower() or "fr" in result, (
            f"Expected error referencing unsupported lang; got {result!r}"
        )

    async def test_switch_to_same_lang_is_noop(self) -> None:
        """switch_language('en') when active_lang is already 'en' → no change.

        req: multilingual-015 — redundant switch avoided gracefully
        """
        deps = _make_deps(active_lang="en")
        ctx = _MockCtx(deps=deps)

        result = await switch_language(ctx, "en")  # type: ignore[arg-type]

        assert deps.lang_switch_requested is None, (
            "lang_switch_requested must remain None for same-language 'switch'"
        )
        # active_lang stays "en"
        assert deps.active_lang == "en"
        assert "already" in result.lower(), f"Expected 'already' in no-op message; got {result!r}"

    async def test_switch_updates_active_lang_immediately(self) -> None:
        """Verify deps.active_lang is updated to the new lang (not just lang_switch_requested).

        req: multilingual-015 — _reconcile_language reads deps.active_lang in output_validator
        """
        deps = _make_deps(active_lang="en")
        ctx = _MockCtx(deps=deps)

        await switch_language(ctx, "es")  # type: ignore[arg-type]

        # Both fields must be updated so the output_validator and boundary both work.
        assert deps.active_lang == "es"
        assert deps.lang_switch_requested == "es"


# ===========================================================================
# Unit tests — end_session tool function (direct call, mock ctx)
# req: evaluation-015
# ===========================================================================


class TestEndSessionTool:
    """Direct unit tests for the end_session tool function.

    Calls the function with a duck-typed mock context so no agent run is needed.
    """

    async def test_end_session_sets_session_ended_flag(self) -> None:
        """end_session() → deps.session_ended = True.

        req: evaluation-015 — tool signals boundary to schedule evaluate_conversation
        """
        deps = _make_deps()
        ctx = _MockCtx(deps=deps)

        result = await end_session(ctx)  # type: ignore[arg-type]

        assert deps.session_ended is True, (
            f"Expected deps.session_ended=True after end_session; got {deps.session_ended!r}"
        )
        # Confirm returns a non-empty string the model can use.
        assert result, "end_session must return a non-empty confirmation string"

    async def test_end_session_custom_reason(self) -> None:
        """end_session(reason='no_more_questions') → session_ended=True, reason in message.

        req: evaluation-015 — reason parameter accepted without error
        """
        deps = _make_deps()
        ctx = _MockCtx(deps=deps)

        result = await end_session(ctx, reason="no_more_questions")  # type: ignore[arg-type]

        assert deps.session_ended is True
        assert "no_more_questions" in result, f"Expected reason in confirmation; got {result!r}"

    async def test_end_session_default_reason(self) -> None:
        """end_session() without explicit reason uses 'user_goodbye' default.

        req: evaluation-015 — default reason is human-readable
        """
        deps = _make_deps()
        ctx = _MockCtx(deps=deps)

        result = await end_session(ctx)  # type: ignore[arg-type]

        assert "user_goodbye" in result, (
            f"Expected default reason 'user_goodbye' in confirmation; got {result!r}"
        )


# ===========================================================================
# Integration test — switch_language via FunctionModel agent run
# req: multilingual-015 — model calls the tool; output_validator sees updated deps
# ===========================================================================


class TestSwitchLanguageModelCall:
    """Integration: FunctionModel simulates model calling switch_language('es').

    Verifies that after the agent run:
    - deps.active_lang == 'es' (tool updated it)
    - deps.lang_switch_requested == 'es' (boundary signal set)
    - output.active_lang == 'es' (_reconcile_language validator reads updated deps)

    req: multilingual-015
    """

    async def test_model_calls_switch_language_updates_deps_and_output(self) -> None:
        """FunctionModel that calls switch_language('es') → deps + output both updated.

        Simulates the full orchestrator run where the model decides to switch to Spanish.
        _reconcile_language sets output.active_lang = deps.active_lang = 'es'.

        req: multilingual-015 (TestModel: model calls the tool)
        """
        deps = _make_deps(active_lang="en")

        with get_orchestrator().override(model=_make_switch_language_model("es", _VALID_TURN_ES)):
            result = await get_orchestrator().run(
                "Please switch to Spanish.",
                deps=deps,
            )

        # Tool updated deps.active_lang in-place.
        assert deps.active_lang == "es", (
            f"Expected deps.active_lang='es' after switch_language tool; got {deps.active_lang!r}"
        )
        # Tool set the boundary signal.
        assert deps.lang_switch_requested == "es", (
            f"Expected deps.lang_switch_requested='es'; got {deps.lang_switch_requested!r}"
        )
        # _reconcile_language validator set output.active_lang from deps.active_lang.
        assert result.output.active_lang == "es", (
            f"Expected output.active_lang='es'; got {result.output.active_lang!r}"
        )

    async def test_switch_language_unsupported_leaves_active_lang_unchanged(self) -> None:
        """FunctionModel calls switch_language with unsupported lang → no-op.

        TestModel calls switch_language with generated arg (seed=0 → 'a', not supported).
        deps.active_lang stays 'en'; output_validator enforces 'en' output.

        req: multilingual-015 — unsupported target rejected gracefully
        """
        deps = _make_deps(active_lang="en")

        # TestModel(call_tools=["switch_language"]) calls the tool with generated args
        # (seed=0 → target_lang='a', not in supported set) → tool rejects it, no state change.
        with get_orchestrator().override(
            model=TestModel(call_tools=["switch_language"], custom_output_args=_VALID_TURN_EN)
        ):
            result = await get_orchestrator().run(
                "Hello!",
                deps=deps,
            )

        # Tool rejected the unsupported lang → deps.lang_switch_requested stays None.
        assert deps.lang_switch_requested is None, (
            "lang_switch_requested must remain None when target lang is not supported"
        )
        # active_lang unchanged → output_validator sets output.active_lang to 'en'.
        assert result.output.active_lang == "en", (
            f"Expected output.active_lang='en' (unchanged); got {result.output.active_lang!r}"
        )


# ===========================================================================
# Integration test — end_session via FunctionModel agent run
# req: evaluation-015 — model calls the tool; boundary reads deps.session_ended
# ===========================================================================


class TestEndSessionModelCall:
    """Integration: FunctionModel simulates model calling end_session.

    Verifies that after the agent run deps.session_ended is True — the boundary
    (_run_orchestrator_turn in chat.py) reads this flag to schedule evaluate_conversation.

    req: evaluation-015
    """

    async def test_model_calls_end_session_sets_session_ended_flag(self) -> None:
        """FunctionModel that calls end_session → deps.session_ended = True after run.

        The chat boundary reads this flag from deps to schedule evaluate_conversation
        instead of using the old is_goodbye keyword heuristic.

        req: evaluation-015 (TestModel: model calls the tool)
        """
        deps = _make_deps(active_lang="en")

        with get_orchestrator().override(model=_make_end_session_model(_VALID_TURN_EN)):
            result = await get_orchestrator().run(
                "Goodbye, that's all I needed!",
                deps=deps,
            )

        # Tool set deps.session_ended — boundary will schedule evaluate_conversation.
        assert deps.session_ended is True, (
            f"Expected deps.session_ended=True after end_session tool; got {deps.session_ended!r}"
        )
        # The run still completes normally with a valid TurnOutput.
        assert result.output.reply, "Expected non-empty reply even after end_session"

    async def test_end_session_not_called_leaves_flag_false(self) -> None:
        """When end_session is NOT called, deps.session_ended stays False.

        Verifies that the flag is not spuriously set on non-goodbye turns.
        req: evaluation-015 — flag only set by the tool, not by default
        """
        deps = _make_deps(active_lang="en")

        with get_orchestrator().override(
            model=TestModel(call_tools=[], custom_output_args=_VALID_TURN_EN)
        ):
            await get_orchestrator().run(
                "What courses do you offer?",
                deps=deps,
            )

        assert deps.session_ended is False, (
            "deps.session_ended must remain False when end_session tool was not called"
        )


# ===========================================================================
# Regression — is_goodbye removed (no dangling refs)
# req: evaluation-015
# ===========================================================================


class TestIsGoodbyeRemoved:
    """Verify is_goodbye has been fully removed from app.eval.runtime.

    After evaluation-015's switch to the end_session tool, the keyword-heuristic
    function must not exist anywhere in the runtime module.

    req: evaluation-015 — is_goodbye replaced by the end_session tool
    """

    def test_is_goodbye_not_in_runtime_module(self) -> None:
        """app.eval.runtime must not export is_goodbye (dangling-ref check).

        req: evaluation-015 — removal verified at module level
        """
        import app.eval.runtime as runtime_module

        assert not hasattr(runtime_module, "is_goodbye"), (
            "is_goodbye must be removed from app.eval.runtime; "
            "the end_session tool now handles goodbye intent detection."
        )

    def test_is_goodbye_not_importable(self) -> None:
        """Importing is_goodbye from app.eval.runtime must raise ImportError/AttributeError.

        req: evaluation-015
        """
        import importlib

        import pytest as _pytest

        with _pytest.raises((ImportError, AttributeError)):
            mod = importlib.import_module("app.eval.runtime")
            _ = mod.is_goodbye  # attribute access is the test


# ===========================================================================
# Orchestrator cache fixture
# ===========================================================================

# The conftest autouse _clear_orchestrator_cache fixture clears get_orchestrator().
# We add a module-level autouse fixture to also clear the faq_agent cache so tests
# that hit the full orchestrator (FunctionModel) don't get a stale agent with
# the wrong model.


@pytest.fixture(autouse=True)
def _clear_faq_agent_cache() -> Generator[None, None, None]:
    """Clear get_faq_agent lru_cache before and after each test.

    Prevents a stale faq_agent (built with incorrect env vars in a prior test)
    from bleeding into integration tests here.
    """
    from app.agents.faq import get_faq_agent

    get_faq_agent.cache_clear()
    yield
    get_faq_agent.cache_clear()
