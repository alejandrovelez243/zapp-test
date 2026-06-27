"""Unit tests for app/guardrails/adapter.py.

Covers:
  - input_name / output_name mapping (known + unknown + passthrough)
  - category_for priority ordering + empty-list fallback
  - secret_input_guard: API key patterns block; benign passes
  - toxicity_output_guard: toxic reply blocks; benign passes
  - secret_output_guard: prompt-fragment and API key patterns block; benign passes
  - pii_output_guard: email in reply blocks; benign passes
  - Fail-safe: _FAIL_SAFE_RESULT has tripwire_triggered=True

req: guardrails-002, guardrails-008, guardrails-009, guardrails-010,
     guardrails-017, guardrails-019
"""

from __future__ import annotations

from app.contract import TurnOutput
from app.guardrails.adapter import (
    _FAIL_SAFE_RESULT,
    category_for,
    input_name,
    output_name,
    pii_output_guard,
    secret_input_guard,
    secret_output_guard,
    toxicity_output_guard,
)

# ===========================================================================
# input_name — map package guard names to contract vocabulary
# ===========================================================================


class TestInputName:
    def test_prompt_injection_maps_to_itself(self) -> None:
        assert input_name("prompt_injection") == "prompt_injection"

    def test_pii_detector_maps_to_itself(self) -> None:
        assert input_name("pii_detector") == "pii_detector"

    def test_toxicity_detector_maps_to_toxicity(self) -> None:
        assert input_name("toxicity_detector") == "toxicity"

    def test_secret_input_maps_to_secret_leak(self) -> None:
        assert input_name("secret_input") == "secret_leak"

    def test_guardrail_error_maps_to_itself(self) -> None:
        assert input_name("guardrail_error") == "guardrail_error"

    def test_unknown_name_passes_through(self) -> None:
        """Unknown guard names are passed through unchanged (fail-open).

        req: guardrails-017
        """
        assert input_name("unknown_guard_xyz") == "unknown_guard_xyz"


# ===========================================================================
# output_name — map package output-guard names to contract vocabulary
# ===========================================================================


class TestOutputName:
    def test_toxicity_output_maps_to_toxicity(self) -> None:
        assert output_name("toxicity_output") == "toxicity"

    def test_secret_output_maps_to_secret_leak(self) -> None:
        assert output_name("secret_output") == "secret_leak"

    def test_pii_output_maps_to_pii_leak(self) -> None:
        assert output_name("pii_output") == "pii_leak"

    def test_guardrail_error_maps_to_itself(self) -> None:
        assert output_name("guardrail_error") == "guardrail_error"

    def test_unknown_name_passes_through(self) -> None:
        assert output_name("mystery_guard") == "mystery_guard"


# ===========================================================================
# category_for — priority ordering + fail-safes
# ===========================================================================


class TestCategoryFor:
    def test_prompt_injection_has_highest_priority(self) -> None:
        """prompt_injection beats all others.

        req: guardrails-019
        """
        names = ["pii_detector", "toxicity", "prompt_injection", "secret_leak"]
        assert category_for(names) == "prompt_injection"

    def test_toxicity_beats_secret_leak(self) -> None:
        assert category_for(["secret_leak", "toxicity"]) == "toxicity"

    def test_secret_leak_beats_pii_detector(self) -> None:
        assert category_for(["pii_detector", "secret_leak"]) == "secret_leak"

    def test_pii_detector_beats_pii_leak(self) -> None:
        assert category_for(["pii_leak", "pii_detector"]) == "pii_detector"

    def test_single_name_returned(self) -> None:
        assert category_for(["pii_leak"]) == "pii_leak"

    def test_empty_list_returns_prompt_injection(self) -> None:
        """Empty list falls back to 'prompt_injection' (fail-safe hardest blocker).

        req: guardrails-019
        """
        assert category_for([]) == "prompt_injection"

    def test_unknown_names_return_first(self) -> None:
        """Names not in the priority list: returns first element."""
        assert category_for(["weird_guard_a", "weird_guard_b"]) == "weird_guard_a"


# ===========================================================================
# Fail-safe result
# ===========================================================================


class TestFailSafeResult:
    def test_fail_safe_triggers_block(self) -> None:
        """_FAIL_SAFE_RESULT has tripwire_triggered=True.

        req: guardrails-019
        """
        assert _FAIL_SAFE_RESULT["tripwire_triggered"] is True
        assert _FAIL_SAFE_RESULT.get("severity") == "critical"


# ===========================================================================
# secret_input_guard — blocks API keys / JWT tokens in user input
# ===========================================================================


class TestSecretInputGuard:
    async def test_openai_key_triggers(self) -> None:
        """sk-<20+ alphanum> in prompt → tripwire_triggered=True.

        req: guardrails-010
        """
        guard = secret_input_guard()
        result = await guard.validate(
            "Here is the key: sk-abcdefghijklmnopqrstuvwxyz01234567890",
            ctx=None,  # type: ignore[arg-type]
        )
        assert result["tripwire_triggered"] is True

    async def test_gateway_key_triggers(self) -> None:
        """pylf_v1_us_... key in prompt → tripwire_triggered=True.

        req: guardrails-010
        """
        guard = secret_input_guard()
        result = await guard.validate(
            "My key is pylf_v1_us_testkey123abc",
            ctx=None,  # type: ignore[arg-type]
        )
        assert result["tripwire_triggered"] is True

    async def test_benign_prompt_passes(self) -> None:
        """Clean philosophy question → tripwire_triggered=False.

        req: guardrails-010
        """
        guard = secret_input_guard()
        result = await guard.validate(
            "What philosophy courses does Zapp offer?",
            ctx=None,  # type: ignore[arg-type]
        )
        assert result["tripwire_triggered"] is False

    def test_guard_has_correct_name(self) -> None:
        """secret_input_guard() returns InputGuardrail with name='secret_input'."""
        guard = secret_input_guard()
        assert guard.name == "secret_input"


# ===========================================================================
# toxicity_output_guard — blocks toxic model replies
# ===========================================================================


def _make_turn(reply: str) -> TurnOutput:
    """Build a minimal TurnOutput for output-guard testing."""
    return TurnOutput(
        reply=reply,
        detected_lang="en",
        active_lang="en",
        lang_confidence=0.9,
        final_normalized_text=reply,
        detected_country=None,
        confidence_score=0.9,
        needs_review=False,
    )


class TestToxicityOutputGuard:
    async def test_toxic_reply_triggers(self) -> None:
        """Reply with a threat → tripwire_triggered=True.

        req: guardrails-009
        """
        guard = toxicity_output_guard()
        turn = _make_turn("I'll kill you if you don't stop asking questions.")
        result = await guard.validate(turn, ctx=None)  # type: ignore[arg-type]
        assert result["tripwire_triggered"] is True

    async def test_clean_reply_passes(self) -> None:
        """Benign philosophy reply → tripwire_triggered=False.

        req: guardrails-009
        """
        guard = toxicity_output_guard()
        turn = _make_turn(
            "Zapp Global Philosophy School offers courses in Stoicism, Ethics, and Logic."
        )
        result = await guard.validate(turn, ctx=None)  # type: ignore[arg-type]
        assert result["tripwire_triggered"] is False

    def test_guard_has_correct_name(self) -> None:
        assert toxicity_output_guard().name == "toxicity_output"


# ===========================================================================
# secret_output_guard — blocks API keys / prompt fragments in model replies
# ===========================================================================


class TestSecretOutputGuard:
    async def test_api_key_in_reply_triggers(self) -> None:
        """sk-... key in reply → tripwire_triggered=True.

        req: guardrails-010
        """
        guard = secret_output_guard()
        turn = _make_turn(
            "Here is the API key you requested: sk-abcdefghijklmnopqrstuvwxyz01234567890"
        )
        result = await guard.validate(turn, ctx=None)  # type: ignore[arg-type]
        assert result["tripwire_triggered"] is True

    async def test_prompt_fragment_triggers(self) -> None:
        """'I am instructed to' phrase in reply → tripwire_triggered=True.

        req: guardrails-010
        """
        guard = secret_output_guard()
        turn = _make_turn("I am instructed to help you with philosophy courses at Zapp School.")
        result = await guard.validate(turn, ctx=None)  # type: ignore[arg-type]
        assert result["tripwire_triggered"] is True

    async def test_benign_reply_passes(self) -> None:
        """Benign reply → tripwire_triggered=False.

        req: guardrails-010
        """
        guard = secret_output_guard()
        turn = _make_turn("Zapp offers courses on Stoicism, Existentialism, and Logic.")
        result = await guard.validate(turn, ctx=None)  # type: ignore[arg-type]
        assert result["tripwire_triggered"] is False

    def test_guard_has_correct_name(self) -> None:
        assert secret_output_guard().name == "secret_output"


# ===========================================================================
# pii_output_guard — blocks PII in model replies
# ===========================================================================


class TestPiiOutputGuard:
    async def test_email_in_reply_triggers(self) -> None:
        """Email address in reply → tripwire_triggered=True.

        req: guardrails-008
        """
        guard = pii_output_guard()
        turn = _make_turn("The student's email is leaked@example.com — please contact them.")
        result = await guard.validate(turn, ctx=None)  # type: ignore[arg-type]
        assert result["tripwire_triggered"] is True

    async def test_benign_reply_passes(self) -> None:
        """Reply with no PII → tripwire_triggered=False.

        req: guardrails-008
        """
        guard = pii_output_guard()
        turn = _make_turn("Zapp Philosophy School offers Stoicism and Logic courses.")
        result = await guard.validate(turn, ctx=None)  # type: ignore[arg-type]
        assert result["tripwire_triggered"] is False

    def test_guard_has_correct_name(self) -> None:
        assert pii_output_guard().name == "pii_output"
