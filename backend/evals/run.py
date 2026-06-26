"""backend/evals/run.py — pydantic-evals gating entrypoint.

Usage (cwd: backend/):
    uv run python -m evals.run

CI (uses the cheaper JUDGE_MODEL_CI):
    EVAL_CI=1 uv run python -m evals.run

Architecture (evaluation-001, evaluation-008, evaluation-009):
1. Load three committed YAML datasets (happy, multilingual, adversarial).
2. Attach evaluators by ``metadata.suite``:
       happy / multilingual → TaskSuccess + LanguageFidelity + SubjectiveQualityJudge
       adversarial          → GuardrailHit + SubjectiveQualityJudge
3. Run ``dataset.evaluate_sync(run_turn)`` for each suite.
4. Compute aggregate metrics (evaluation-002 through -006).
5. Render ONE markdown report to ``evals/reports/latest-report.md`` (evaluation-009).
6. Compare every metric to ``THRESHOLDS``; skip ``DEFERRED_THRESHOLDS`` keys
   (evaluation-007, evaluation-008).
7. ``sys.exit(1)`` if any threshold is breached; ``sys.exit(0)`` otherwise.

Judge errors (evaluation-019): an exception raised by SubjectiveQualityJudge is
caught by pydantic-evals and stored in ``case.evaluator_failures``; the case is
still present in ``report.cases`` but lacks a score key.  Such cases are counted
as un-judged (score = 0) so they pull ``judge_mean`` down and may trigger a breach
— they do NOT crash the run.

CI model swap (evaluation-010): ``EVAL_CI=1`` patches ``evals.judge.JUDGE_MODEL``
to ``JUDGE_MODEL_CI`` before the first call to ``get_judge()``, keeping per-PR
costs low without changing any call site.

pydantic-evals API used (probed 2026-06):
    Dataset.from_file(path)                       → Dataset
    Dataset.add_evaluator(evaluator)               → None
    Dataset.evaluate_sync(task_fn)                 → EvaluationReport
    EvaluationReport.cases                         → list[ReportCase]
    EvaluationReport.failures                      → list[ReportCaseFailure]
    ReportCase.assertions  dict[str, EvaluationResult[bool]]
    ReportCase.scores      dict[str, EvaluationResult[int|float]]
    ReportCase.task_duration (float, seconds)
    ReportCase.output      (the dict returned by run_turn)
    ReportCase.inputs / .metadata
    ReportCaseFailure.task_duration / .metadata

Satisfies: evaluation-001, evaluation-006, evaluation-007, evaluation-008,
           evaluation-009, evaluation-019.
"""

from __future__ import annotations

import os
import statistics
import sys
from pathlib import Path
from typing import Any

from pydantic_evals import Dataset
from pydantic_evals.reporting import EvaluationReport

from evals.config import (
    DEFERRED_THRESHOLDS,
    JUDGE_MODEL_CI,
    PRICE_TABLE,
    THRESHOLDS,
    lower_is_better,
)
from evals.evaluators import (
    GuardrailHit,
    LanguageFidelity,
    SubjectiveQualityJudge,
    TaskSuccess,
)
from evals.report import write_report
from evals.task import run_turn

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
DATASETS_DIR = _HERE / "datasets"

# ---------------------------------------------------------------------------
# CI judge-model swap (evaluation-010)
# Must happen BEFORE the first call to get_judge(), which is lazy/cached.
# We patch the module-level name so the lru_cache picks it up on first call.
# ---------------------------------------------------------------------------
if os.environ.get("EVAL_CI") == "1":
    import evals.judge as _judge_mod

    _judge_mod.JUDGE_MODEL = JUDGE_MODEL_CI


# ---------------------------------------------------------------------------
# Internal pipeline steps (exposed for testing / verify scripts)
# ---------------------------------------------------------------------------


def _load_and_annotate_datasets() -> dict[str, Dataset]:
    """Load the three committed YAML datasets and attach evaluators by suite.

    Evaluator assignment (design.md §3.5):
    - happy / multilingual: TaskSuccess + LanguageFidelity + SubjectiveQualityJudge
    - adversarial: GuardrailHit + SubjectiveQualityJudge

    Returns a dict keyed by suite name.
    """
    happy = Dataset.from_file(DATASETS_DIR / "happy.yaml")
    multilingual = Dataset.from_file(DATASETS_DIR / "multilingual.yaml")
    adversarial = Dataset.from_file(DATASETS_DIR / "adversarial.yaml")

    for ds in (happy, multilingual):
        ds.add_evaluator(TaskSuccess())
        ds.add_evaluator(LanguageFidelity())
        ds.add_evaluator(SubjectiveQualityJudge())

    adversarial.add_evaluator(GuardrailHit())
    adversarial.add_evaluator(SubjectiveQualityJudge())

    return {"happy": happy, "multilingual": multilingual, "adversarial": adversarial}


def _run_datasets(
    datasets: dict[str, Dataset],
) -> dict[str, EvaluationReport]:
    """Run evaluate_sync(run_turn) for each dataset. Returns {suite: report}."""
    reports: dict[str, EvaluationReport] = {}
    for suite, dataset in datasets.items():
        print(f"\n[evals] Running suite: {suite} ({len(dataset.cases)} cases)")
        report = dataset.evaluate_sync(run_turn, progress=True)
        report.print(include_input=False, include_output=False)
        reports[suite] = report
    return reports


def _extract_score(case: Any, key: str) -> int | float | None:
    """Return the numeric value for *key* from case.scores, or None if absent."""
    er = case.scores.get(key)
    return er.value if er is not None else None


def _extract_assertion(case: Any, key: str) -> bool | None:
    """Return the boolean value for *key* from case.assertions, or None if absent."""
    er = case.assertions.get(key)
    return er.value if er is not None else None


def _compute_metrics(
    reports: dict[str, EvaluationReport],
) -> dict[str, float]:
    """Aggregate all metrics from the three suite reports.

    Returns a flat dict with keys matching THRESHOLDS plus informational extras
    (latency_p50_ms).

    Evaluation-019 contract: SubjectiveQualityJudge errors leave the case in
    report.cases but without a score key → score treated as 0 (not-passing).
    Task-level failures (run_turn raised) land in report.failures → counted as
    failed for task_success, language_fidelity, and judge_mean.
    """
    happy_r = reports["happy"]
    ml_r = reports["multilingual"]
    adv_r = reports["adversarial"]

    happy_cases = list(happy_r.cases)
    ml_cases = list(ml_r.cases)
    adv_cases = list(adv_r.cases)

    happy_fails = list(happy_r.failures)
    ml_fails = list(ml_r.failures)
    adv_fails = list(adv_r.failures)

    # -----------------------------------------------------------------------
    # 1. Task success rate — happy + multilingual  (evaluation-002)
    # -----------------------------------------------------------------------
    task_cases = happy_cases + ml_cases
    task_fail_count = len(happy_fails) + len(ml_fails)
    total_task = len(task_cases) + task_fail_count

    task_pass = sum(1 for c in task_cases if _extract_assertion(c, "TaskSuccess") is True)
    task_success_rate = task_pass / total_task if total_task > 0 else 0.0

    # -----------------------------------------------------------------------
    # 2. Language fidelity — happy + multilingual  (evaluation-003, -020)
    # -----------------------------------------------------------------------
    # Failures count as language-fidelity failures (no reply → wrong language).
    lang_pass = sum(
        1 for c in task_cases if _extract_assertion(c, "reply_matches_active_lang") is True
    )
    language_fidelity = lang_pass / total_task if total_task > 0 else 0.0

    # -----------------------------------------------------------------------
    # 3. Guardrail precision & recall — adversarial only  (evaluation-004)
    # -----------------------------------------------------------------------
    total_tp: int = 0
    total_fn: int = 0
    total_fp: int = 0

    for c in adv_cases:
        tp = _extract_score(c, "tp")
        fn = _extract_score(c, "fn")
        fp = _extract_score(c, "fp")
        total_tp += int(tp) if tp is not None else 0
        total_fn += int(fn) if fn is not None else 0
        total_fp += int(fp) if fp is not None else 0

    # Task failures in adversarial: assume all must_trips were missed (fn += count)
    for f in adv_fails:
        must = set((f.metadata or {}).get("must_trip", []))
        total_fn += len(must)

    # recall = tp / (tp + fn) — missed attacks are the dangerous failure
    guardrail_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    # precision = tp / (tp + fp) — undefined if nothing was blocked → default 1.0
    guardrail_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0

    # -----------------------------------------------------------------------
    # 4. LLM judge mean (1-5) — all suites  (evaluation-005, evaluation-019)
    # -----------------------------------------------------------------------
    all_cases = happy_cases + ml_cases + adv_cases
    total_fail_count = len(happy_fails) + len(ml_fails) + len(adv_fails)

    judge_scores: list[float] = []
    for c in all_cases:
        raw = _extract_score(c, "SubjectiveQualityJudge")
        # None → evaluator errored (evaluation-019: count as 0 / not-passing)
        judge_scores.append(float(raw) if raw is not None else 0.0)
    # Task-level failures are un-judged → append 0 for each
    judge_scores.extend([0.0] * total_fail_count)

    judge_mean = statistics.mean(judge_scores) if judge_scores else 0.0

    # -----------------------------------------------------------------------
    # 5. Latency p50 / p95 — all suites  (evaluation-006)
    # -----------------------------------------------------------------------
    # Collect per-case task durations (ReportCaseFailure has no task_duration).
    durations_ms: list[float] = [c.task_duration * 1000.0 for c in all_cases]

    # Note: ReportCaseFailure has no task_duration field — only ReportCase does.
    # Failures are excluded from latency since their duration is not recorded.
    if len(durations_ms) >= 2:
        # statistics.quantiles returns (n-1) cut-points; with n=100 → indices 0-98
        # p50 = index 49, p95 = index 94
        q = statistics.quantiles(durations_ms, n=100, method="inclusive")
        latency_p50 = q[49]
        latency_p95 = q[94]
    elif durations_ms:
        latency_p50 = latency_p95 = durations_ms[0]
    else:
        latency_p50 = latency_p95 = 0.0

    # -----------------------------------------------------------------------
    # 6. Cost per conversation — all suites  (evaluation-006)
    # -----------------------------------------------------------------------
    # Model key for PRICE_TABLE: strip the gateway/<provider>: prefix.
    # Default to the orchestrator model ("gpt-4.1"); task failures yield no tokens.
    _orch_model_env = os.environ.get("ORCHESTRATOR_MODEL", "gateway/openai:gpt-4.1")
    _model_key = _orch_model_env.split(":")[-1]
    _fallback_prices: dict[str, float] = {"input": 0.4, "output": 1.6}
    prices = PRICE_TABLE.get(_model_key, PRICE_TABLE.get("gpt-4.1-mini", _fallback_prices))

    total_cost_usd = 0.0
    session_ids: set[str] = set()

    for c in all_cases:
        usage: dict[str, int] = {}
        if isinstance(c.output, dict):
            usage = c.output.get("_usage", {}) or {}
        in_tok = int(usage.get("input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        total_cost_usd += (in_tok * prices["input"] + out_tok * prices["output"]) / 1_000_000

        inputs = c.inputs if isinstance(c.inputs, dict) else {}
        sid = inputs.get("session_id") or c.name
        session_ids.add(str(sid))

    distinct_sessions = max(1, len(session_ids))
    cost_per_conversation_usd = total_cost_usd / distinct_sessions

    return {
        "task_success_rate": task_success_rate,
        "language_fidelity": language_fidelity,
        "guardrail_recall": guardrail_recall,
        "guardrail_precision": guardrail_precision,
        "judge_mean": judge_mean,
        "latency_p50_ms": latency_p50,
        "latency_p95_ms": latency_p95,
        "cost_per_conversation_usd": cost_per_conversation_usd,
    }


def _suite_summaries(
    reports: dict[str, EvaluationReport],
) -> dict[str, dict[str, Any]]:
    """Build per-suite summary dicts for the markdown report."""
    summaries: dict[str, dict[str, Any]] = {}
    for suite, rep in reports.items():
        n_cases = len(rep.cases)
        n_fails = len(rep.failures)
        total = n_cases + n_fails
        avg_dur = statistics.mean([c.task_duration for c in rep.cases]) if rep.cases else 0.0
        summaries[suite] = {
            "total_cases": total,
            "task_successes": n_cases,
            "task_failures": n_fails,
            "avg_task_duration_s": round(avg_dur, 4),
        }
    return summaries


def _gate(metrics: dict[str, float]) -> list[str]:
    """Compare metrics to THRESHOLDS; return a list of breach strings.

    Keys in DEFERRED_THRESHOLDS are skipped (evaluation-007).
    lower_is_better() determines the comparison direction (evaluation-008).
    """
    breaches: list[str] = []
    for key, threshold in THRESHOLDS.items():
        if key in DEFERRED_THRESHOLDS:
            continue  # guardrail thresholds deferred until guardrails feature lands
        val = metrics.get(key)
        if val is None:
            continue  # metric not computed for this run
        bad = val > threshold if lower_is_better(key) else val < threshold
        if bad:
            direction = ">" if lower_is_better(key) else "<"
            breaches.append(f"{key}={val:.4f} {direction} threshold={threshold} (breach)")
    return breaches


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Load datasets, run evaluation, compute metrics, write report, gate.

    Exits 0 when all thresholds pass; exits 1 on any breach.
    Judge errors do NOT crash the run (evaluation-019).
    """
    print("[evals] Starting eval suite …")

    datasets = _load_and_annotate_datasets()
    reports = _run_datasets(datasets)

    metrics = _compute_metrics(reports)
    summaries = _suite_summaries(reports)

    # Gate: collect breaches before writing the report so the report shows them
    breaches = _gate(metrics)

    # Write ONE consolidated report (evaluation-009)
    write_report(metrics, summaries, breaches)

    # Print flat metrics dict for CI log parsing (evaluation-008)
    print("METRICS:", metrics)

    if breaches:
        print("EVAL GATE FAILED:")
        for b in breaches:
            print(f"  {b}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
