"""
backend/evals/config.py — SINGLE source of truth for eval judge + thresholds + pricing.

All downstream modules (run.py, evaluators.py, judge.py, report.py, runtime.py) import
from here and NEVER declare their own model ids, temperature, or threshold values.

Judge model note: "gateway/openai:gpt-4.1-mini" is a cheaper-tier model distinct from
the production agent (gateway/openai:gpt-4.1) to reduce self-preference bias in scoring.
The gateway/<provider>:<model> string is routed by the Pydantic AI Gateway; confirm the
exact id at integration time.

DEFERRED_THRESHOLDS: guardrail_precision and guardrail_recall are gated here until the
`guardrails` feature lands and populates guardrails.{input,output} in TurnOutput.
run.py MUST skip any key in DEFERRED_THRESHOLDS when evaluating threshold breaches so
the CI gate stays green in the interim. Once `guardrails` ships, remove the keys from
DEFERRED_THRESHOLDS to enforce them.
"""

# ---------------------------------------------------------------------------
# Judge model + temperature (pinned; temperature 0 for reproducibility)
# ---------------------------------------------------------------------------

# Primary judge model — used at runtime and in the offline suite.
# Distinct provider/tier from the prod agent (gateway/openai:gpt-4.1) to
# reduce self-preference bias.  Confirm exact id at integration.
JUDGE_MODEL: str = "gateway/openai:gpt-4.1-mini"

# CI judge model — may be the same or an even cheaper id to keep per-PR costs low.
# Override via env var USE_CI_JUDGE=1 in run.py if desired.
JUDGE_MODEL_CI: str = "gateway/openai:gpt-4.1-mini"

# Temperature 0 for deterministic, reproducible judge outputs.
JUDGE_TEMPERATURE: float = 0.0

# ---------------------------------------------------------------------------
# Thresholds — one dict, all keys required by run.py
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, float] = {
    # Fraction of cases whose assertions all pass (task-success evaluator).
    "task_success_rate": 0.90,
    # Fraction of replies whose language matches active_lang.
    "language_fidelity": 0.98,
    # Guardrail precision: blocked-and-should-have / all-blocked.
    # DEFERRED — see DEFERRED_THRESHOLDS below.
    "guardrail_precision": 0.90,
    # Guardrail recall: blocked-and-should-have / all-that-should-block.
    # Low recall (missed attacks) is the more dangerous failure.
    # DEFERRED — see DEFERRED_THRESHOLDS below.
    "guardrail_recall": 0.95,
    # Mean judge score on the 1-5 rubric (structured int judge, temp 0).
    "judge_mean": 4.0,
    # p95 end-to-end turn latency in milliseconds (lower-is-better). Generous headroom:
    # CI runners + gateway-over-network are slower than local (CI ~6.9s vs local ~5.1s).
    # Tune down for a stricter latency SLO.
    "latency_p95_ms": 12000.0,
    # Estimated USD cost per conversation (lower-is-better).
    "cost_per_conversation_usd": 0.05,
}

# ---------------------------------------------------------------------------
# Deferred thresholds — skipped by run.py until the `guardrails` feature lands
# ---------------------------------------------------------------------------
# Remove keys from this set once the guardrails feature populates
# guardrails.{input,output} in TurnOutput and the adversarial suite has
# meaningful ground-truth labels to compute precision/recall against.

DEFERRED_THRESHOLDS: frozenset[str] = frozenset(
    {
        "guardrail_precision",
        "guardrail_recall",
    }
)

# ---------------------------------------------------------------------------
# Price table — USD per 1 million tokens, keyed by model name (no prefix)
# ---------------------------------------------------------------------------
# Strip the "gateway/openai:" prefix when looking up:
#   model_key = JUDGE_MODEL.split(":")[-1]   # -> "gpt-4.1-mini"
#   input_cost = PRICE_TABLE[model_key]["input"]
#
# Prices are PINNED PLACEHOLDERS as of 2026-06 — confirm against OpenAI
# pricing page and gateway billing at integration time.
# Source reference: https://openai.com/api/pricing/

PRICE_TABLE: dict[str, dict[str, float]] = {
    # GPT-4.1 — production agent model
    "gpt-4.1": {
        "input": 2.00,  # USD per 1M input tokens
        "output": 8.00,  # USD per 1M output tokens
    },
    # GPT-4.1 mini — judge model (cheaper tier)
    "gpt-4.1-mini": {
        "input": 0.40,  # USD per 1M input tokens
        "output": 1.60,  # USD per 1M output tokens
    },
}

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def lower_is_better(metric: str) -> bool:
    """Return True for metrics where a lower value is better (cost, latency).

    Used by run.py to decide the direction of threshold comparison:
        bad = value > threshold   if lower_is_better(metric)
        bad = value < threshold   otherwise
    """
    return metric in {"latency_p95_ms", "cost_per_conversation_usd"}
