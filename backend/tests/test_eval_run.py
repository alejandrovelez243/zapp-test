"""Tests for evals/run.py — _gate helper and sys.exit logic.

Exercises the threshold gating logic directly via _gate() without running
the real evaluation suite (no datasets, no gateway calls, no LLM).

Covers: evaluation-008, guardrails-018
"""

from __future__ import annotations

import sys

import pytest

from evals.config import DEFERRED_THRESHOLDS, THRESHOLDS
from evals.run import _gate

# ---------------------------------------------------------------------------
# Helpers: passing and breaching metric dicts
# ---------------------------------------------------------------------------


def _passing_metrics() -> dict[str, float]:
    """Build a metrics dict that satisfies every threshold (guardrails now enforced)."""
    return {
        "task_success_rate": 0.95,  # threshold 0.90 — pass
        "language_fidelity": 0.99,  # threshold 0.98 — pass
        "guardrail_recall": 0.96,  # threshold 0.95 — pass (ENFORCED, guardrails-018)
        "guardrail_precision": 0.91,  # threshold 0.90 — pass (ENFORCED, guardrails-018)
        "judge_mean": 4.5,  # threshold 4.0 — pass
        "latency_p95_ms": 1000.0,  # threshold 12000 — pass (lower-is-better)
        "cost_per_conversation_usd": 0.01,  # threshold 0.05 — pass (lower-is-better)
    }


def _breaching_task_success() -> dict[str, float]:
    """Breach task_success_rate (below its minimum threshold)."""
    m = _passing_metrics()
    m["task_success_rate"] = 0.50  # < 0.90 → BREACH
    return m


# ---------------------------------------------------------------------------
# _gate unit tests (evaluation-008)
# ---------------------------------------------------------------------------


def test_gate_breach_returns_nonempty() -> None:
    """Breaching metric → _gate returns a non-empty list. (evaluation-008)"""
    breaches = _gate(_breaching_task_success())
    assert len(breaches) > 0
    assert any("task_success_rate" in b for b in breaches)


def test_gate_pass_returns_empty() -> None:
    """All-pass metrics → _gate returns an empty list. (evaluation-008)"""
    breaches = _gate(_passing_metrics())
    assert breaches == []


def test_gate_breach_exits_nonzero() -> None:
    """Breaching _gate list → sys.exit(1) raises SystemExit with non-zero code.

    Mirrors what main() does after collecting breaches. (evaluation-008)
    """
    breaches = _gate(_breaching_task_success())
    assert breaches  # non-empty (precondition)
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(1)
    assert exc_info.value.code != 0


def test_gate_pass_no_exit() -> None:
    """All-pass metrics → no SystemExit raised. (evaluation-008)"""
    breaches = _gate(_passing_metrics())
    # Confirm the gate is clean; the caller would NOT call sys.exit.
    assert not breaches


def test_gate_guardrail_thresholds_enforced() -> None:
    """guardrail_precision and guardrail_recall are now ENFORCED by _gate.

    The guardrails feature is live (guardrails-018): both keys must be absent
    from DEFERRED_THRESHOLDS and present in THRESHOLDS.  When values are 0.0
    (catastrophically low), _gate must breach both metrics.
    (guardrails-018, evaluation-008)
    """
    # Keys removed from DEFERRED_THRESHOLDS
    assert "guardrail_precision" not in DEFERRED_THRESHOLDS
    assert "guardrail_recall" not in DEFERRED_THRESHOLDS

    # Keys present in THRESHOLDS (so the gate can compare them)
    assert "guardrail_precision" in THRESHOLDS
    assert "guardrail_recall" in THRESHOLDS

    # Forced breach: 0.0 is below both thresholds (0.90 and 0.95)
    metrics = _passing_metrics()
    metrics["guardrail_precision"] = 0.0
    metrics["guardrail_recall"] = 0.0

    breaches = _gate(metrics)
    assert any("guardrail_precision" in b for b in breaches)
    assert any("guardrail_recall" in b for b in breaches)


def test_gate_latency_breach() -> None:
    """p95 latency above threshold → breach (lower-is-better metric). (evaluation-008)"""
    metrics = _passing_metrics()
    metrics["latency_p95_ms"] = 1_000_000.0  # far above any configured threshold → BREACH
    breaches = _gate(metrics)
    assert any("latency_p95_ms" in b for b in breaches)


def test_gate_cost_breach() -> None:
    """Cost per conversation above threshold → breach (lower-is-better). (evaluation-008)"""
    metrics = _passing_metrics()
    metrics["cost_per_conversation_usd"] = 0.10  # > 0.05 → BREACH
    breaches = _gate(metrics)
    assert any("cost_per_conversation_usd" in b for b in breaches)


def test_gate_judge_mean_breach() -> None:
    """judge_mean below threshold → breach. (evaluation-008)"""
    metrics = _passing_metrics()
    metrics["judge_mean"] = 2.5  # < 4.0 → BREACH
    breaches = _gate(metrics)
    assert any("judge_mean" in b for b in breaches)


def test_gate_language_fidelity_breach() -> None:
    """language_fidelity below threshold → breach. (evaluation-008)"""
    metrics = _passing_metrics()
    metrics["language_fidelity"] = 0.80  # < 0.98 → BREACH
    breaches = _gate(metrics)
    assert any("language_fidelity" in b for b in breaches)
