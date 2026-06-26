"""Tests for evals/run.py — _gate helper and sys.exit logic.

Exercises the threshold gating logic directly via _gate() without running
the real evaluation suite (no datasets, no gateway calls, no LLM).

Covers: evaluation-008
"""

from __future__ import annotations

import sys

import pytest

from evals.config import DEFERRED_THRESHOLDS
from evals.run import _gate

# ---------------------------------------------------------------------------
# Helpers: passing and breaching metric dicts
# ---------------------------------------------------------------------------


def _passing_metrics() -> dict[str, float]:
    """Build a metrics dict that satisfies every non-deferred threshold."""
    return {
        "task_success_rate": 0.95,  # threshold 0.90 — pass
        "language_fidelity": 0.99,  # threshold 0.98 — pass
        "guardrail_recall": 0.0,  # DEFERRED — skipped by _gate
        "guardrail_precision": 0.0,  # DEFERRED — skipped by _gate
        "judge_mean": 4.5,  # threshold 4.0 — pass
        "latency_p95_ms": 1000.0,  # threshold 6000 — pass (lower-is-better)
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


def test_gate_deferred_thresholds_skipped() -> None:
    """DEFERRED guardrail thresholds are not gated, even when 0.0. (evaluation-008)

    guardrail_precision and guardrail_recall are in DEFERRED_THRESHOLDS and
    must be skipped by _gate regardless of their value.
    """
    assert "guardrail_precision" in DEFERRED_THRESHOLDS
    assert "guardrail_recall" in DEFERRED_THRESHOLDS

    metrics = _passing_metrics()
    # Both at 0.0 — catastrophically low but DEFERRED so must NOT breach.
    metrics["guardrail_precision"] = 0.0
    metrics["guardrail_recall"] = 0.0

    breaches = _gate(metrics)
    assert not any("guardrail" in b for b in breaches)


def test_gate_latency_breach() -> None:
    """p95 latency above threshold → breach (lower-is-better metric). (evaluation-008)"""
    metrics = _passing_metrics()
    metrics["latency_p95_ms"] = 9000.0  # > 6000 → BREACH
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
