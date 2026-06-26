"""Tests for evals/evaluators.py — TaskSuccess, LanguageFidelity, GuardrailHit.

Probes the real EvaluatorContext shape from pydantic_evals.evaluators and
constructs hand-made instances to exercise each evaluator in isolation (no
gateway / LLM calls required).

Covers: evaluation-002, evaluation-003, evaluation-004, evaluation-020
"""

from __future__ import annotations

from typing import Any

from pydantic_evals.evaluators import EvaluatorContext
from pydantic_evals.otel._errors import SpanTreeRecordingError

from evals.evaluators import GuardrailHit, LanguageFidelity, TaskSuccess

# ---------------------------------------------------------------------------
# Helper: build a minimal EvaluatorContext
# ---------------------------------------------------------------------------


def _ctx(
    output: dict[str, Any],
    expected_output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvaluatorContext:  # type: ignore[type-arg]
    """Build a minimal EvaluatorContext for evaluator unit tests.

    Uses SpanTreeRecordingError as _span_tree because OpenTelemetry is not
    configured in the test environment (the dataclass field is required).
    """
    return EvaluatorContext(
        name="test-case",
        inputs={},
        metadata=metadata,
        expected_output=expected_output,
        output=output,
        duration=0.1,
        _span_tree=SpanTreeRecordingError("no otel in test"),
        attributes={},
        metrics={},
    )


# ---------------------------------------------------------------------------
# TaskSuccess (evaluation-002)
# ---------------------------------------------------------------------------


class TestTaskSuccessEvaluator:
    def test_task_success_pass(self) -> None:
        """Matching expected fields + needs_review=False → True. (evaluation-002)"""
        ctx = _ctx(
            output={"active_lang": "es", "needs_review": False, "reply": "Hola"},
            expected_output={"active_lang": "es"},
        )
        assert TaskSuccess().evaluate(ctx) is True

    def test_task_success_field_mismatch(self) -> None:
        """Wrong expected field value → False. (evaluation-002)"""
        ctx = _ctx(
            output={"active_lang": "en", "needs_review": False},
            expected_output={"active_lang": "es"},
        )
        assert TaskSuccess().evaluate(ctx) is False

    def test_task_success_unexpected_needs_review(self) -> None:
        """needs_review=True without expected → False. (evaluation-002)"""
        ctx = _ctx(
            output={"active_lang": "es", "needs_review": True},
            expected_output={"active_lang": "es"},
        )
        assert TaskSuccess().evaluate(ctx) is False

    def test_task_success_expected_needs_review_true(self) -> None:
        """Case explicitly expects needs_review=True (fallback) → True. (evaluation-002)"""
        ctx = _ctx(
            output={"active_lang": "en", "needs_review": True},
            expected_output={"active_lang": "en", "needs_review": True},
        )
        assert TaskSuccess().evaluate(ctx) is True

    def test_task_success_expected_needs_review_false_explicit(self) -> None:
        """expected_output specifies needs_review=False; output matches → True.

        Regression guard: when expected_output explicitly declares needs_review=False,
        the field-match loop already verified it; the final gate must be skipped so
        no redundant double-check occurs.  This mirrors fusion Cases that assert
        needs_review=false for happy-path geo turns. (evaluation-002)
        """
        ctx = _ctx(
            output={"active_lang": "es", "needs_review": False, "reply": "Hola"},
            expected_output={"active_lang": "es", "needs_review": False},
        )
        assert TaskSuccess().evaluate(ctx) is True

    def test_task_success_needs_review_gate_skipped_when_in_expected(self) -> None:
        """The final needs_review gate is skipped whenever expected_output names needs_review.

        Regression guard: the gate (needs_review is False) must NOT fire when
        expected_output explicitly declares needs_review — the field-match loop already
        verified it for both True and False values.  Covers the language-fallback Case
        pattern (evaluation-020) that expects needs_review=True. (evaluation-002)
        """
        # Branch A: explicit False in expected — loop verified it, gate skipped.
        ctx_false = _ctx(
            output={"active_lang": "es", "needs_review": False},
            expected_output={"active_lang": "es", "needs_review": False},
        )
        assert TaskSuccess().evaluate(ctx_false) is True

        # Branch B: explicit True in expected — loop verified it, gate skipped.
        ctx_true = _ctx(
            output={"active_lang": "en", "needs_review": True},
            expected_output={"active_lang": "en", "needs_review": True},
        )
        assert TaskSuccess().evaluate(ctx_true) is True


# ---------------------------------------------------------------------------
# LanguageFidelity (evaluation-003, evaluation-020)
# ---------------------------------------------------------------------------


class TestLanguageFidelityEvaluator:
    def test_language_fidelity_es_reply_active_es_pass(self) -> None:
        """Spanish reply + active_lang=es → reply_matches_active_lang=True. (evaluation-003)"""
        ctx = _ctx(
            output={
                "reply": (
                    "El seminario de estoicismo es el martes por la tarde"
                    " en la escuela de filosofía."
                ),
                "active_lang": "es",
            }
        )
        result = LanguageFidelity().evaluate(ctx)
        assert isinstance(result, dict)
        assert result["reply_matches_active_lang"] is True

    def test_language_fidelity_en_reply_active_es_fail(self) -> None:
        """English reply + active_lang=es → reply_matches_active_lang=False. (evaluation-020)

        The reply is well above the 12-char minimum for reliable detection.
        """
        ctx = _ctx(
            output={
                "reply": (
                    "The stoicism seminar takes place every Tuesday afternoon at the "
                    "Zapp Global Philosophy School."
                ),
                "active_lang": "es",
            }
        )
        result = LanguageFidelity().evaluate(ctx)
        assert isinstance(result, dict)
        # Reply is 91 chars → is_reliable=True (threshold is 12 chars).
        assert result["is_reliable"] is True
        assert result["detected"] == "en"
        assert result["reply_matches_active_lang"] is False


# ---------------------------------------------------------------------------
# GuardrailHit (evaluation-004)
# ---------------------------------------------------------------------------


class TestGuardrailHitEvaluator:
    def test_guardrail_hit_tp_fn_fp_all_match(self) -> None:
        """must_trip fired + guardrail fired → tp=1, fn=0, fp=0. (evaluation-004)"""
        ctx = _ctx(
            output={"guardrails": {"input": ["prompt_injection"], "output": []}},
            metadata={"must_trip": ["prompt_injection"]},
        )
        result = GuardrailHit().evaluate(ctx)
        assert result["tp"] == 1
        assert result["fn"] == 0
        assert result["fp"] == 0
        assert result["expected_block"] is True
        assert result["did_block"] is True

    def test_guardrail_hit_fn_missed_attack(self) -> None:
        """must_trip set but no guardrail fired → fn=1 (dangerous miss). (evaluation-004)"""
        ctx = _ctx(
            output={"guardrails": {"input": [], "output": []}},
            metadata={"must_trip": ["prompt_injection"]},
        )
        result = GuardrailHit().evaluate(ctx)
        assert result["tp"] == 0
        assert result["fn"] == 1
        assert result["fp"] == 0
        assert result["expected_block"] is True
        assert result["did_block"] is False

    def test_guardrail_hit_fp_false_alarm(self) -> None:
        """must_trip empty but guardrail fired → fp=1 (false alarm). (evaluation-004)"""
        ctx = _ctx(
            output={"guardrails": {"input": ["pii_detector"], "output": []}},
            metadata={"must_trip": []},
        )
        result = GuardrailHit().evaluate(ctx)
        assert result["tp"] == 0
        assert result["fn"] == 0
        assert result["fp"] == 1
        assert result["expected_block"] is False
        assert result["did_block"] is True
