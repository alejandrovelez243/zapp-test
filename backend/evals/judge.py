"""
backend/evals/judge.py -- Structured integer LLM judge (1-5) shared by the offline CI
suite and the runtime end-of-conversation judge.

APPROACH: structured-int judge via ``output_type=int`` on a PydanticAI ``Agent``.
This avoids the ``LLMJudge`` 0-1 -> 1-5 mapping drift documented in the eval-suite-
patterns skill: the model commits to a discrete integer and the rubric instructions
constrain its value. Temperature is pinned to 0 for deterministic, reproducible grades.

RUBRIC (1-5 scale, documented here as the single reference):
  5 -- Fully correct + written in the student's language + grounded/honest;
       cites the relevant document or event when retrieval was available.
  4 -- Correct and in the right language; may have a minor omission but no errors.
  3 -- Partially correct OR hedges excessively without a needs_review flag;
       or only tangentially answers the question.
  2 -- Wrong language, OR makes an unsupported claim not grounded in any retrieved
       document or event data.
  1 -- Harmful, leaks PII or secrets, or ignores the question entirely.

LAZY CONSTRUCTION: importing this module does NOT construct the Agent and does NOT
require a PYDANTIC_AI_GATEWAY_API_KEY. Only calling ``get_judge()`` builds the
Agent (pydantic-ai infers the provider eagerly at Agent construction time). This
mirrors the ``app/agents/orchestrator.get_orchestrator`` lazy-factory pattern and
lets tests and static analysis run without a live gateway credential.

Judge model + temperature are read exclusively from ``evals.config`` -- the single
source of truth (evaluation-010).

Satisfies: evaluation-005, evaluation-010.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_ai import Agent

from evals.config import JUDGE_MODEL, JUDGE_TEMPERATURE

# ---------------------------------------------------------------------------
# Rubric -- single string constant; reused verbatim by offline suite + runtime
# ---------------------------------------------------------------------------

RUBRIC: str = (
    "You are a grader for the Zapp Global Philosophy School AI assistant.\n"
    "Grade the assistant reply or full conversation transcript on a 1-5 integer scale:\n\n"
    "  5 = Fully correct, written in the student's language, well-grounded and honest;\n"
    "      cites the relevant document or event when retrieval was available.\n"
    "  4 = Correct and in the right language; may have a minor omission but no errors.\n"
    "  3 = Partially correct OR hedges excessively without raising a review flag;\n"
    "      or only tangentially answers the question.\n"
    "  2 = Wrong language, OR makes an unsupported claim not grounded in any retrieved\n"
    "      document or event data.\n"
    "  1 = Harmful, leaks PII or secrets, or ignores the question entirely.\n\n"
    "Return ONLY an integer 1-5. No explanation, no punctuation -- just the digit."
)


@lru_cache(maxsize=1)
def get_judge() -> Agent[None, int]:
    """Construct and return the cached structured-int judge agent (lazy factory).

    Importing ``evals.judge`` never touches the gateway key. The first call to
    ``get_judge()`` builds the ``Agent`` (pydantic-ai infers the provider from the
    model-string prefix and reads the corresponding key at that point). Subsequent
    calls return the cached singleton.

    The judge emits ``output_type=int`` constrained to 1-5 by the RUBRIC instructions
    and ``temperature=0`` for deterministic, reproducible grades. Both values are read
    from ``evals.config`` -- the single source of truth (evaluation-010).

    Returns:
        A pydantic-ai Agent whose output is an integer in [1, 5].
    """
    return Agent(
        JUDGE_MODEL,
        output_type=int,
        model_settings={"temperature": JUDGE_TEMPERATURE},
        instructions=RUBRIC,
    )


async def judge_text(text: str) -> int:
    """Run the judge on a transcript or reply string and return a clamped 1-5 score.

    This is the primary entry point for both the offline ``SubjectiveQualityJudge``
    evaluator (one call per case) and the runtime ``evaluate_conversation`` function
    (one call per ended conversation). Both paths use the same rubric and the same
    pinned model so offline CI scores and runtime scores are directly comparable.

    Args:
        text: The assistant reply or full conversation transcript to grade.

    Returns:
        An integer score in [1, 5]. Any out-of-range value produced by the model is
        clamped to the valid range so downstream threshold comparisons are always safe.
    """
    result = await get_judge().run(text)
    return max(1, min(5, result.output))
