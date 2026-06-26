"""backend/evals/report.py — assemble and render the ONE consolidated eval report.

Called by ``evals.run.main()`` after all datasets are evaluated.  The report is
written to ``backend/evals/reports/latest-report.md`` and a short summary is
printed to stdout.

Satisfies: evaluation-009 (write report to file AND print summary).
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from evals.config import DEFERRED_THRESHOLDS, THRESHOLDS, lower_is_better

REPORTS_DIR = Path(__file__).parent / "reports"


def _status(key: str, val: float) -> str:
    """Return a gate status string for a metric and its threshold."""
    if key not in THRESHOLDS:
        return "INFO"
    if key in DEFERRED_THRESHOLDS:
        return "DEFERRED"
    threshold = THRESHOLDS[key]
    if lower_is_better(key):
        return "PASS" if val <= threshold else "FAIL"
    return "PASS" if val >= threshold else "FAIL"


def write_report(
    metrics: dict[str, float],
    suite_summaries: dict[str, dict[str, Any]],
    breaches: list[str],
    report_path: Path | None = None,
) -> Path:
    """Render the markdown report, write it to disk, and print a summary.

    Parameters
    ----------
    metrics:
        Flat dict of all computed metrics (task_success_rate, language_fidelity,
        guardrail_recall, guardrail_precision, judge_mean, latency_p50_ms,
        latency_p95_ms, cost_per_conversation_usd, ...).
    suite_summaries:
        Per-suite aggregated stats (case counts, pass counts, durations).
    breaches:
        List of human-readable threshold-breach strings produced by ``_gate()``.
    report_path:
        Override the default ``REPORTS_DIR/latest-report.md``.

    Returns
    -------
    Path
        Absolute path of the written report file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = report_path or REPORTS_DIR / "latest-report.md"

    now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    lines: list[str] = [
        "# Zapp Global Philosophy School — Eval Report",
        "",
        f"**Generated:** {now}",
        "",
        "---",
        "",
        "## Overall Metrics",
        "",
        "| Metric | Value | Threshold | Status |",
        "|--------|------:|----------:|--------|",
    ]

    # Defined display order (informational + gated metrics together)
    _ordered_keys = [
        "task_success_rate",
        "language_fidelity",
        "guardrail_recall",
        "guardrail_precision",
        "judge_mean",
        "latency_p50_ms",
        "latency_p95_ms",
        "cost_per_conversation_usd",
    ]
    # Include any extra keys not in the ordered list at the end
    extra_keys = [k for k in metrics if k not in _ordered_keys]
    display_order = _ordered_keys + extra_keys

    for key in display_order:
        val = metrics.get(key)
        if val is None:
            continue
        threshold = THRESHOLDS.get(key, "—")
        status = _status(key, val)

        thr_str = f"{threshold}" if isinstance(threshold, float) else str(threshold)
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)

        lines.append(f"| {key} | {val_str} | {thr_str} | {status} |")

    lines.extend(["", "---", "", "## Per-Suite Summary", ""])

    for suite, summary in suite_summaries.items():
        lines.append(f"### {suite.capitalize()}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        for k, v in summary.items():
            if isinstance(v, float):
                lines.append(f"| {k} | {v:.4f} |")
            elif isinstance(v, int):
                lines.append(f"| {k} | {v} |")
            else:
                lines.append(f"| {k} | {v} |")
        lines.append("")

    lines.extend(["---", "", "## Gate Result", ""])

    if breaches:
        lines.append("**STATUS: EVAL GATE FAILED**")
        lines.append("")
        lines.append("Threshold breaches:")
        lines.append("")
        for b in breaches:
            lines.append(f"- {b}")
    else:
        lines.append("**STATUS: ALL THRESHOLDS PASSED**")

    lines.append("")
    content = "\n".join(lines)
    path.write_text(content, encoding="utf-8")

    # Print summary to stdout (evaluation-009)
    _print_summary(path, metrics, breaches)
    return path


def _print_summary(
    path: Path,
    metrics: dict[str, float],
    breaches: list[str],
) -> None:
    """Print a concise summary of the eval run to stdout."""
    print()
    print("=" * 60)
    print("EVAL SUITE SUMMARY")
    print("=" * 60)
    for key, val in metrics.items():
        status = _status(key, val)
        if isinstance(val, float):
            print(f"  {key:<38} {val:.4f}  [{status}]")
        else:
            print(f"  {key:<38} {val}  [{status}]")
    print("-" * 60)
    if breaches:
        print(f"GATE: FAILED ({len(breaches)} breach(es))")
        for b in breaches:
            print(f"  BREACH: {b}")
    else:
        print("GATE: PASSED")
    print(f"Report: {path}")
    print("=" * 60)
    print()
