"""Tests for GuardedAgent wiring in app/agents/orchestrator.py.

Verifies:
  - get_guarded_orchestrator() returns a GuardedAgent instance
  - It wraps the same underlying Agent returned by get_orchestrator()
  - Input guard names match the expected set
  - Output guard names match the expected set
  - guardrails_llm_enabled=True adds llm_judge guard

req: guardrails-001, guardrails-002, guardrails-003, guardrails-004,
     guardrails-005, guardrails-006, guardrails-009, guardrails-010
"""

from __future__ import annotations

import pytest
from pydantic_ai_guardrails import GuardedAgent

from app.agents.orchestrator import get_guarded_orchestrator, get_orchestrator


class TestGuardedOrchestratorWiring:
    def test_returns_guarded_agent_instance(self) -> None:
        """get_guarded_orchestrator() returns a GuardedAgent.

        req: guardrails-001
        """
        guarded = get_guarded_orchestrator()
        assert isinstance(guarded, GuardedAgent)

    def test_wraps_orchestrator_agent(self) -> None:
        """get_guarded_orchestrator()._agent is get_orchestrator().

        Ensures the GuardedAgent wraps the exact same pydantic-ai Agent
        instance so .override() on get_orchestrator() also affects guarded runs.

        req: guardrails-001
        """
        guarded = get_guarded_orchestrator()
        underlying = get_orchestrator()
        # GuardedAgent stores the wrapped agent as ._agent
        assert guarded._agent is underlying

    def test_input_guard_names_match_expected(self) -> None:
        """Input guards are exactly the four expected guards.

        Expected:
          - prompt_injection  (req: guardrails-003, -004)
          - toxicity_detector (req: guardrails-005)
          - pii_detector      (req: guardrails-006)
          - secret_input      (req: guardrails-010)

        req: guardrails-002
        """
        guarded = get_guarded_orchestrator()
        # GuardedAgent exposes .input_guardrails as the list of InputGuardrail objects.
        input_names = {g.name for g in guarded.input_guardrails}
        expected = {"prompt_injection", "toxicity_detector", "pii_detector", "secret_input"}
        assert input_names == expected, (
            f"Input guard names mismatch. Expected {expected!r}, got {input_names!r}"
        )

    def test_output_guard_names_match_expected(self) -> None:
        """Output guards are exactly the three expected guards (when llm_judge disabled).

        Expected:
          - toxicity_output   (req: guardrails-009)
          - secret_output     (req: guardrails-010)
          - pii_output        (req: guardrails-008)

        req: guardrails-002
        """
        guarded = get_guarded_orchestrator()
        output_names = {g.name for g in guarded.output_guardrails}
        expected = {"toxicity_output", "secret_output", "pii_output"}
        assert output_names == expected, (
            f"Output guard names mismatch. Expected {expected!r}, got {output_names!r}"
        )

    def test_llm_judge_added_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """guardrails_llm_enabled=True appends llm_judge to output guards.

        req: guardrails-001 (task 5: llm_judge gate)
        """
        monkeypatch.setenv("GUARDRAILS_LLM_ENABLED", "true")
        # Also set a valid judge model env var so settings parses correctly.
        monkeypatch.setenv("JUDGE_MODEL", "openai:gpt-4o-mini")

        from app.config import get_settings

        get_settings.cache_clear()
        get_guarded_orchestrator.cache_clear()

        guarded = get_guarded_orchestrator()
        output_names = {g.name for g in guarded.output_guardrails}
        assert "llm_judge" in output_names, (
            f"Expected 'llm_judge' in output guards when GUARDRAILS_LLM_ENABLED=true; "
            f"got {output_names!r}"
        )

    def test_is_cached(self) -> None:
        """get_guarded_orchestrator() is idempotent (lru_cache).

        Same object returned on repeated calls in one test — re-construction
        only happens after cache_clear() (done between tests by conftest fixture).

        req: guardrails-001
        """
        first = get_guarded_orchestrator()
        second = get_guarded_orchestrator()
        assert first is second
