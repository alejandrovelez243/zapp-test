"""Orchestrator agent — emits the per-turn ``TurnOutput`` contract in the locked language.

Builds the PydanticAI orchestrator with ``output_type=TurnOutput`` (the canonical nine-field
per-turn contract), dynamic instructions that inject the session's locked ``active_lang``, and
an ``output_validator`` that fuses the LLM's self-reported ``detected_lang`` with the
deterministic ``lingua`` detector to set ``lang_confidence`` and the language ``needs_review``
triggers, repairing the reply language if the model drifts.

Agent construction is LAZY: importing this module requires NO provider API key. Only the
first call to ``get_orchestrator()`` instantiates the ``Agent`` (which triggers provider-key
resolution in pydantic-ai 2.0). This mirrors ``app/db.py``'s lazy-engine pattern and lets
the FastAPI app boot, run migrations, and serve ``/health`` without any LLM credential in
the environment.

Resilience (FallbackModel / timeouts / boundary exception handling) and ``UsageLimits`` are
applied at the FastAPI boundary (Task 9) — this module is just the agent + validator.

Satisfies:
  multilingual-001 — emit the full nine-field TurnOutput contract on every turn
  multilingual-005 — lang_confidence is the LLM-vs-detector agreement score
  multilingual-006 — reply rendered in active_lang; lang_confidence recomputed
  multilingual-007 — locked active_lang enforced on the output
  multilingual-010 — low-confidence → keep active_lang, ask user to confirm, needs_review
  multilingual-012 — detector failure → low lang_confidence + needs_review

Design contract: specs/multilingual/design.md §2.4
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_ai import Agent, ModelRetry, RunContext

from app.config import get_settings
from app.contract import TurnOutput
from app.deps import AgentDeps
from app.lang.detector import LanguageDetector
from app.lang.fusion import compute_lang_confidence

# --- Static base instructions (NOT system_prompt — persona must not leak across agents) ---
_BASE_INSTRUCTIONS = (
    "You are the orchestrator for the Zapp Global Philosophy School assistant. "
    "Help prospective and current students with questions about the school, its "
    "philosophy courses, and its events. Always emit the full per-turn JSON contract "
    "with all nine fields populated."
)


@lru_cache(maxsize=1)
def _reply_language_detector() -> LanguageDetector:
    """Return a process-wide deterministic detector used to verify the reply language.

    Built once (lingua model load is expensive) over the default supported set. This is a
    stateless, read-only helper — not mutable module state — so a cached singleton is the
    idiomatic choice and keeps the output_validator from rebuilding lingua per call.
    """
    return LanguageDetector()


def _with_active_language(ctx: RunContext[AgentDeps]) -> str:
    """Inject the locked ``active_lang`` into the per-run instructions (multilingual-007)."""
    active_lang = ctx.deps.active_lang
    return (
        f"Reply ONLY in {active_lang}. "
        "Detect and self-report the language the user wrote in this turn as `detected_lang` "
        "(ISO 639-1, two lowercase letters). Set `final_normalized_text` to the cleaned user "
        "text. Set `detected_country` to null. Use sensible placeholder values for "
        "`confidence_score` and `lang_confidence` — they are reconciled after your turn."
    )


async def _reconcile_language(ctx: RunContext[AgentDeps], output: TurnOutput) -> TurnOutput:
    """Fuse the LLM and detector signals and enforce the language contract on the output.

    Order matters: guard partials first, then reconcile. Output validators ALSO run on
    streaming partials, so a structurally half-built ``output`` must short-circuit before any
    cross-field logic (per pydantic-ai-conventions §4).
    """
    # MANDATORY guard — never validate a half-built streaming partial.
    if ctx.partial_output:
        return output

    deps = ctx.deps
    settings = get_settings()

    # 1. lang_confidence = agreement score between the LLM self-report and the detector.
    #    req: multilingual-005
    output.lang_confidence = compute_lang_confidence(output.detected_lang, deps.detection)

    # 2. Force the locked language onto the contract (the session owns active_lang).
    #    req: multilingual-003, multilingual-007
    output.active_lang = deps.active_lang

    # 3. Reply-language enforcement: deterministically check the reply is in active_lang.
    #    Only act on a reliable, non-None detection so trivially short replies (which lingua
    #    cannot classify) do not cause spurious retries.
    #    req: multilingual-006, multilingual-007
    reply_detection = _reply_language_detector().detect(output.reply)
    if (
        reply_detection.lang is not None
        and reply_detection.is_reliable
        and reply_detection.lang != deps.active_lang
    ):
        raise ModelRetry(
            f"Reply must be written in {deps.active_lang}; it was written in "
            f"{reply_detection.lang}. Rewrite the reply in {deps.active_lang}."
        )

    # 4. needs_review from the state-machine decision and detector failure.
    #    req: multilingual-008, multilingual-009 (fallback) — multilingual-012 (detector failed)
    if deps.lang_decision.fallback_used or deps.lang_decision.needs_review:
        output.needs_review = True
    if deps.detection.lang is None:
        # Detector failed/yielded no signal → fall back to the LLM detected_lang, damp the
        # confidence, and flag for review. req: multilingual-012
        output.lang_confidence = min(output.lang_confidence, 0.3)
        output.needs_review = True

    # 5. Low-confidence clarification: keep active_lang, flag review, and ask the user to
    #    confirm their language ONCE. ``ctx.retry`` guards against an infinite retry loop —
    #    after the single clarification attempt we accept the turn with needs_review set.
    #    req: multilingual-010
    if output.lang_confidence < settings.lang_confidence_min:
        output.needs_review = True
        if ctx.retry < 1:
            raise ModelRetry(
                "Language confidence is low. Ask the user to confirm which language they "
                f"want to use, written in {deps.active_lang}."
            )

    return output


@lru_cache(maxsize=1)
def get_orchestrator() -> Agent[AgentDeps, TurnOutput]:
    """Construct and return the cached orchestrator agent (lazy factory).

    Importing this module never touches a provider key. The first call to
    ``get_orchestrator()`` builds the ``Agent`` (which resolves the provider from the model
    string prefix, e.g. ``anthropic:`` -> reads ``ANTHROPIC_API_KEY``), registers the
    dynamic instructions and output validator, then caches the result for the process
    lifetime.

    The pattern mirrors ``app/db.py``'s ``get_engine()`` — construction on first use, not on
    import — so migrations, health checks, and static analysis never require LLM credentials.
    """
    agent: Agent[AgentDeps, TurnOutput] = Agent(
        get_settings().orchestrator_model,  # model id from the ONE config module
        deps_type=AgentDeps,
        output_type=TurnOutput,
        instructions=_BASE_INSTRUCTIONS,
        retries=2,
    )
    # Register dynamic per-run instructions and the cross-field output validator on the
    # freshly constructed agent. Calling agent.instructions(fn) / agent.output_validator(fn)
    # is identical to using @agent.instructions / @agent.output_validator as decorators —
    # both append the function to the agent's internal lists. req: multilingual-007 / -005.
    agent.instructions(_with_active_language)
    agent.output_validator(_reconcile_language)
    return agent
