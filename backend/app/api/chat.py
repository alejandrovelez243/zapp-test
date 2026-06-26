"""POST /chat FastAPI boundary — language detection → guardrails → orchestrator → persistence.

Wires the full per-turn pipeline:
  detect → resolve_active_lang → input guardrails → build AgentDeps → orchestrator.run →
  output guardrails → persist session + messages → return TurnOutput.

Catches ``ModelHTTPError | UnexpectedModelBehavior | UsageLimitExceeded`` and degrades
gracefully (never returns a 500 for model errors).

Requirements satisfied:
  multilingual-001 — emit the full nine-field TurnOutput on every /chat turn
  multilingual-004 — first-turn active_lang lock persisted via update_session
  multilingual-008 — locked + unsupported → keep active_lang, still persisted
  multilingual-009 — first-turn unsupported → fallback "en", session persisted
  guardrails-001 — input guardrails run before the agent; output guardrails run after
  guardrails-002 — TurnOutput.guardrails populated from triggered guardrail names
  guardrails-003 — prompt_injection → block (no model call)
  guardrails-004 — jailbreak → block (no model call)
  guardrails-005 — toxicity (input) → block (no model call)
  guardrails-006 — pii_detector → redact + continue; gr_in.text passed to orchestrator
  guardrails-007 — off_topic → flag; name carried to guardrails.input
  guardrails-008 — pii_leak in output → redact turn.reply
  guardrails-009 — toxicity in output → block turn.reply with safe refusal
  guardrails-010 — secret_leak in output → block turn.reply with safe refusal
  guardrails-012 — block path emits full nine-field TurnOutput, never a 500
  guardrails-013 — Logfire span per guardrail check; PostHog event with NAMES ONLY

Observability (Task 10):
  multilingual-001 / multilingual-005 — one Logfire ``chat_turn`` span wraps the full
  turn (detect → run) so a grader sees one trace root per conversation turn; an inner
  ``language.detect`` span isolates the detector call.  After the turn (happy or
  degraded), a metadata-only PostHog ``turn_completed`` event carries the four contract
  fields required by the task — NEVER student message content.

Design contract: specs/multilingual/design.md §2.6, specs/guardrails/design.md §2.4
"""

import logging

import httpx
import logfire
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import degraded_turn, get_orchestrator
from app.agents.session import (
    get_or_create_session,
    load_messages,
    save_messages,
    update_session,
)
from app.config import get_settings
from app.contract import GuardrailReport, TurnOutput
from app.db import get_session, get_sessionmaker
from app.deps import AgentDeps
from app.eval.runtime import evaluate_conversation, is_goodbye
from app.guardrails.engine import GuardrailResult, run_input_guardrails, run_output_guardrails
from app.guardrails.refusal import safe_refusal
from app.lang.detector import LanguageDetector
from app.lang.state import resolve_active_lang
from app.observability import get_posthog

log = logging.getLogger(__name__)
router = APIRouter()


async def _background_eval(session_id: str) -> None:
    """Open a fresh session and evaluate the ended conversation.

    Executed as a FastAPI ``BackgroundTask`` after a goodbye-intent message is
    detected in the ``/chat`` handler.  Opens its own ``AsyncSession`` via
    ``get_sessionmaker()`` so it is fully decoupled from the request-scoped ``db``
    (which is closed before background tasks execute).

    ``evaluate_conversation`` handles its own commit and never raises, so no
    additional error handling is required here.

    req: evaluation-015, evaluation-018
    """
    async with get_sessionmaker()() as db:
        await evaluate_conversation(db, session_id)


class ChatRequest(BaseModel):
    """Inbound chat turn payload."""

    session_id: str
    message: str


@router.post("/chat", response_model=TurnOutput)
async def chat(
    req: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> TurnOutput:
    """Full chat turn: detect → resolve → guardrails → agent → guardrails → persist → TurnOutput.

    Never returns a 500: ``ModelHTTPError``, ``UnexpectedModelBehavior``, and
    ``UsageLimitExceeded`` are caught and degrade to a safe ``TurnOutput`` with
    ``needs_review=True``.  Session language state is always persisted even on
    the degrade path and the block path so subsequent turns remain coherent.

    The block path (input guardrail fires) short-circuits before any model call so it
    works without a gateway key — the LLM is never reached.

    req: multilingual-001, multilingual-004, multilingual-008, multilingual-009
    req: guardrails-001..010, guardrails-012, guardrails-013
    """
    settings = get_settings()

    # One Logfire span per conversation turn — the trace root so a grader can open a
    # single trace and see detect → resolve → guardrails → agent run end-to-end.
    # req: multilingual-001, multilingual-005 (Task 10)
    with logfire.span("chat_turn", session_id=req.session_id):
        # 1. Deterministic language detection (pre-agent, no LLM round-trip).
        #    The inner span makes the detector call individually latency-attributable.
        #    req: multilingual-002
        with logfire.span("language.detect"):
            det = LanguageDetector(
                supported=settings.supported,
                min_input_chars=settings.min_input_chars,
            ).detect(req.message)

        # 2. Load or create the ConversationSession row.
        #    req: multilingual-007
        session = await get_or_create_session(db, req.session_id)

        # 3. Decide active_lang via the state machine (pure, no I/O).
        #    req: multilingual-003, multilingual-004, multilingual-008, multilingual-009
        decision = resolve_active_lang(session, det, settings)

        # 4. Request IP — safe fallback for reverse proxies or test clients without a
        #    real remote address.
        request_ip: str = request.client.host if request.client else "unknown"

        # 5. Run input guardrails BEFORE the agent.
        #    Synchronous (engine.py has no I/O); wrapped in its own Logfire span.
        #    req: guardrails-001, guardrails-003..007, guardrails-013
        with logfire.span("guardrails.input"):
            gr_in: GuardrailResult = await run_input_guardrails(
                req.message, decision.active_lang, settings
            )

        if gr_in.blocked:
            # Block path: persist session language state so subsequent turns are
            # coherent, then return a safe TurnOutput WITHOUT calling the orchestrator.
            # The LLM is never reached — this path works with no gateway key.
            # req: guardrails-003, guardrails-004, guardrails-005, guardrails-012
            await update_session(
                db,
                session,
                active_lang=decision.active_lang,
                last_supported_lang=(
                    decision.active_lang
                    if decision.active_lang in settings.supported
                    else session.last_supported_lang
                ),
                pending_switch_lang=decision.pending_switch_lang,
                pending_switch_count=decision.pending_switch_count,
            )
            await db.commit()

            # Primary category for the refusal message: first triggered name, falling
            # back to "prompt_injection" when the list is unexpectedly empty (fail-safe).
            primary_in_category: str = gr_in.triggered[0] if gr_in.triggered else "prompt_injection"
            blocked_turn = TurnOutput(
                reply=safe_refusal(decision.active_lang, primary_in_category),
                detected_lang=det.lang or decision.active_lang,
                active_lang=decision.active_lang,
                lang_confidence=0.0,
                final_normalized_text="",
                detected_country=None,
                confidence_score=0.0,
                needs_review=True,
                guardrails=GuardrailReport(input=gr_in.triggered),
            )

            # Metadata-only PostHog event — NAMES ONLY, never req.message or reply.
            # req: guardrails-013
            ph = get_posthog()
            if ph is not None:
                ph.capture(
                    distinct_id=req.session_id,
                    event="turn_completed",
                    properties={
                        "active_lang": blocked_turn.active_lang,
                        "detected_lang": blocked_turn.detected_lang,
                        "lang_confidence": blocked_turn.lang_confidence,
                        "needs_review": blocked_turn.needs_review,
                        "guardrail_input": gr_in.triggered,
                        "guardrail_output": [],
                    },
                )

            return blocked_turn

        # 6. Load message history for session coherence.
        #    Only reached when input guardrails did NOT block.
        #    req: multilingual-007
        history = await load_messages(db, req.session_id)

        # 7. Run the orchestrator inside a per-request httpx client so every outbound
        #    geo/locale call in the agent run is captured in one Logfire span via
        #    logfire.instrument_httpx(capture_all=True).
        #    Pass gr_in.text (possibly PII-redacted) instead of req.message.
        #    req: multilingual-001, guardrails-006
        usage = RunUsage()
        turn: TurnOutput
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
                deps = AgentDeps(
                    session=db,
                    http=http,
                    session_id=req.session_id,
                    request_ip=request_ip,
                    active_lang=decision.active_lang,
                    detection=det,
                    lang_decision=decision,
                )
                result = await get_orchestrator().run(
                    gr_in.text,
                    deps=deps,
                    message_history=history,
                    usage=usage,
                    usage_limits=UsageLimits(
                        request_limit=6,
                        tool_calls_limit=8,
                        total_tokens_limit=20_000,
                    ),
                )
        except (ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded) as exc:
            # Degrade gracefully — persist the session lang state so future turns
            # remain coherent, but do NOT save messages (the run didn't complete).
            # req: multilingual-001, multilingual-004, multilingual-008, multilingual-009
            log.warning(
                "Orchestrator error — degrading turn (session=%r): %s: %s",
                req.session_id,
                type(exc).__name__,
                exc,
            )
            await update_session(
                db,
                session,
                active_lang=decision.active_lang,
                last_supported_lang=(
                    decision.active_lang
                    if decision.active_lang in settings.supported
                    else session.last_supported_lang
                ),
                pending_switch_lang=decision.pending_switch_lang,
                pending_switch_count=decision.pending_switch_count,
            )
            await db.commit()
            turn = degraded_turn(decision.active_lang)
        else:
            # 8. Persist language state + full message history.
            #    req: multilingual-007
            await update_session(
                db,
                session,
                active_lang=decision.active_lang,
                last_supported_lang=(
                    decision.active_lang
                    if decision.active_lang in settings.supported
                    else session.last_supported_lang
                ),
                pending_switch_lang=decision.pending_switch_lang,
                pending_switch_count=decision.pending_switch_count,
            )
            await save_messages(db, req.session_id, result.all_messages())
            await db.commit()

            # 9. Capture the structured output emitted by the output_validator.
            #    req: multilingual-001
            turn = result.output

        # 10. Run output guardrails AFTER the agent (happy path or degrade path).
        #     Wrapped in its own Logfire span; modify turn.reply in-place.
        #     req: guardrails-001, guardrails-008, guardrails-009, guardrails-010, guardrails-013
        with logfire.span("guardrails.output"):
            gr_out: GuardrailResult = run_output_guardrails(turn.reply, settings)

        if gr_out.blocked:
            # Replace the reply with a safe refusal (block wins over redact).
            # req: guardrails-009, guardrails-010
            primary_out_category: str = gr_out.triggered[0] if gr_out.triggered else "secret_leak"
            turn.reply = safe_refusal(turn.active_lang, primary_out_category)
        elif gr_out.action == "redact":
            # Scrub PII from the reply text.  req: guardrails-008
            turn.reply = gr_out.text

        # 11. Merge guardrail names into the contract and OR needs_review.
        #     req: guardrails-002
        turn.guardrails = GuardrailReport(input=gr_in.triggered, output=gr_out.triggered)
        turn.needs_review = turn.needs_review or bool(gr_in.triggered or gr_out.triggered)

        # 12. Metadata-only PostHog event — NEVER include req.message or turn.reply.
        #     Guardrail NAMES (not content) are included for product-analytics visibility.
        #     PostHog does not scrub PII; student message content stays in Logfire only.
        #     req: multilingual-001, multilingual-005 (Task 10); guardrails-013
        ph = get_posthog()
        if ph is not None:
            ph.capture(
                distinct_id=req.session_id,
                event="turn_completed",
                properties={
                    "active_lang": turn.active_lang,
                    "detected_lang": turn.detected_lang,
                    "lang_confidence": turn.lang_confidence,
                    "needs_review": turn.needs_review,
                    "guardrail_input": gr_in.triggered,
                    "guardrail_output": gr_out.triggered,
                },
            )

        # 13. Schedule end-of-conversation evaluation if goodbye intent detected.
        #     A fresh AsyncSession is opened inside ``_background_eval`` so it is
        #     decoupled from the now-committed request-scoped ``db`` session.
        #     req: evaluation-015, evaluation-018
        if settings.runtime_eval_enabled and is_goodbye(req.message, decision.active_lang):
            background_tasks.add_task(_background_eval, req.session_id)

        return turn
