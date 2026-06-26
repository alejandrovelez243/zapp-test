---
description: Thin wrapper — run the one-command eval suite and surface the report path and exit code.
argument-hint: (none)
---

Run the eval suite and surface the machine-readable result. This is a thin wrapper (no test suite, no diagnosis — use `/verify` for the full gate).

## Run
!uv run python -m evals.run

## Report
- Echo the process **exit code** (0 = pass; non-zero = threshold breach, because `evals.run` computes thresholds and calls `sys.exit(1)` itself).
- Echo the eval **report path** printed by the run (the pydantic-evals report, with per-Case scores and the latency percentiles computed via `statistics.quantiles`).
- One line: PASS (exit 0) or FAIL (non-zero) plus the count of failing Cases if shown. Nothing else.
