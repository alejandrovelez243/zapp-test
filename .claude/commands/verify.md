---
description: SDD gate 5 — run the one-command eval suite, report pass/fail and any threshold breach, and run pytest if present.
argument-hint: (none)
---

You are the **verification gate**. Run the project's eval suite and test suite, then report a clear PASS/FAIL with evidence. Do not edit code to make things pass — diagnose and report.

## 1. Run the eval suite (one command)
!uv run python -m evals.run

## 2. Run the test suite if present
- If a `tests/` directory or `pytest.ini`/`pyproject` pytest config exists, run: `uv run pytest -q`. If pytest is not configured, say so and skip.

## 3. Report
- State **PASS** only if the eval run exits 0 AND pytest (when present) passes. Otherwise **FAIL**.
- For any **threshold breach**, name the specific metric and its limit, e.g.: a failed eval **Case id** (which maps to a requirement id), accuracy/judge-score below threshold, p50/p95 **latency** over budget, or **cost-per-conversation** over budget. Quote the offending numbers from the report.
- Surface the eval **report path** and the process **exit code** verbatim.
- Remind the reviewer that the report ties each Case id back to its requirement id (SDD traceability). If FAIL, recommend the next action: re-run `/implement <feature> <task>` for the owning specialist, or open the failing Case.
- Do NOT commit. Verification is read-only.
