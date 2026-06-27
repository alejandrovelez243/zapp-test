"""POST /chat FastAPI boundary — language detection → guardrails → orchestrator → persistence.

Wires the full per-turn pipeline:
  detect → resolve_active_lang → build AgentDeps → guarded-orchestrator.run →
  persist session + messages → return TurnOutput.

With ``guardrails_enabled=True`` (default) the turn runs through
``get_guarded_orchestrator()`` (a ``GuardedAgent`` wrapping the orchestrator).
  - ``InputGuardrailViolation`` → safe-refusal ``TurnOutput`` before any model call.
  - ``OutputGuardrailViolation`` → safe-refusal reply; guardrails.output populated.
With ``guardrails_enabled=False`` the plain orchestrator is used directly.

Catches ``ModelHTTPError | UnexpectedModelBehavior | UsageLimitExceeded`` and
degrades gracefully (never returns a 500 for model errors).

Requirements satisfied:
  multilingual-001 — emit the full nine-field TurnOutput on every /chat turn
  multilingual-004 — first-turn active_lang lock persisted via update_language_state
  multilingual-008 — locked + unsupported → keep active_lang, still persisted
  multilingual-009 — first-turn unsupported → fallback "en", session persisted
  guardrails-001 — input guardrails run before the model; output guardrails after
  guardrails-002 — TurnOutput.guardrails populated from triggered guardrail names
  guardrails-003 — prompt_injection → block (no model call)
  guardrails-004 — jailbreak → block (no model call; merged into prompt_injection)
  guardrails-005 — toxicity (input) → block (no model call)
  guardrails-006 — pii_detector → block + refusal; name recorded in guardrails.input
  guardrails-007 — off-topic handling (framework's toxicity guard catches extreme cases)
  guardrails-008 — pii in output → block; pii_output guard fires
  guardrails-009 — toxicity in output → block; toxicity_output guard fires
  guardrails-010 — secret in input or output → block; names recorded
  guardrails-012 — block path emits full nine-field TurnOutput, never a 500
  guardrails-013 — Logfire span per turn; PostHog event with NAMES ONLY (no content)
  guardrails-016 — guardrails_enabled=False → plain orchestrator, guardrails empty

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
from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_ai_guardrails import InputGuardrailViolation, OutputGuardrailViolation
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import (
    degraded_turn,
    get_guarded_orchestrator,
    get_orchestrator,
)
from app.agents.session import ConversationSession, SessionRepository
from app.config import Settings, get_settings
from app.contract import GuardrailReport, TurnOutput
from app.db import get_session, get_sessionmaker
from app.deps import AgentDeps
from app.eval.runtime import evaluate_conversation, is_goodbye
from app.fusion.geo import GeoContext, GeoFusionService
from app.guardrails.adapter import category_for, input_name, output_name
from app.guardrails.refusal import safe_refusal
from app.lang.detector import DetectionResult
from app.lang.pipeline import LanguagePipeline
from app.lang.state import ActiveLangDecision
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


# ---------------------------------------------------------------------------
# Module-level helpers — each handles one seam of the per-turn pipeline.
# ---------------------------------------------------------------------------


def _detect_language(message: str, pipeline: LanguagePipeline) -> DetectionResult:
    """Run deterministic language detection inside a named Logfire span.

    req: multilingual-002
    """
    with logfire.span("language.detect"):
        return pipeline.detect(message)


async def _persist_language_state(
    repo: SessionRepository,
    session: ConversationSession,
    db: AsyncSession,
    decision: ActiveLangDecision,
    settings: Settings,
) -> None:
    """Write active_lang + pending-switch counters back to the session row (no commit).

    Shared by the block path, the degrade path, and the happy path so the logic
    lives in exactly one place.

    req: multilingual-004, multilingual-007, multilingual-008, multilingual-009
    """
    await repo.update_language_state(
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


def _emit_telemetry(
    session_id: str,
    turn: TurnOutput,
    gr_in_triggered: list[str],
    gr_out_triggered: list[str],
) -> None:
    """Emit a metadata-only ``turn_completed`` PostHog event.

    Never includes student message content — PostHog does not scrub PII.
    Guardrail NAMES (not content) are included for product-analytics visibility.

    req: multilingual-001, multilingual-005 (Task 10); guardrails-013
    """
    ph = get_posthog()
    if ph is not None:
        ph.capture(
            distinct_id=session_id,
            event="turn_completed",
            properties={
                "active_lang": turn.active_lang,
                "detected_lang": turn.detected_lang,
                "lang_confidence": turn.lang_confidence,
                "needs_review": turn.needs_review,
                "guardrail_input": gr_in_triggered,
                "guardrail_output": gr_out_triggered,
            },
        )


def _build_agent_deps(
    db: AsyncSession,
    http: httpx.AsyncClient,
    session_id: str,
    request_ip: str,
    decision: ActiveLangDecision,
    det: DetectionResult,
    geo: GeoContext,
) -> AgentDeps:
    """Construct the per-request AgentDeps from resolved signals.

    req: orchestrator-and-fusion-002, multilingual-005, multilingual-012
    """
    return AgentDeps(
        session=db,
        http=http,
        session_id=session_id,
        request_ip=request_ip,
        active_lang=decision.active_lang,
        detection=det,
        lang_decision=decision,
        geo=geo,
    )


def _build_block_turn(
    active_lang: str,
    det: DetectionResult,
    *,
    in_names: list[str] | None = None,
    out_names: list[str] | None = None,
    geo_country: str | None = None,
) -> TurnOutput:
    """Build a safe-refusal TurnOutput for the input-block or output-block path.

    All nine contract fields are populated.  ``needs_review=True`` signals the turn
    was blocked.  ``geo_country`` is only set when a geo call completed (output-block);
    input-blocks short-circuit before geo is useful.

    req: guardrails-012 — full nine-field TurnOutput, never a 500
    req: guardrails-011 — reply in active_lang
    """
    all_names = (in_names or []) + (out_names or [])
    primary = category_for(all_names)
    return TurnOutput(
        reply=safe_refusal(active_lang, primary),
        detected_lang=det.lang or active_lang,
        active_lang=active_lang,
        lang_confidence=0.0,
        final_normalized_text="",
        detected_country=geo_country,
        confidence_score=0.0,
        needs_review=True,
        guardrails=GuardrailReport(
            input=in_names or [],
            output=out_names or [],
        ),
    )


async def _run_turn(
    *,
    db: AsyncSession,
    repo: SessionRepository,
    session: ConversationSession,
    decision: ActiveLangDecision,
    det: DetectionResult,
    session_id: str,
    request_ip: str,
    message: str,
    history: list[ModelMessage] | None,
    settings: Settings,
) -> TurnOutput:
    """Geo-resolve → build deps → run (guarded or plain) orchestrator; degrade on errors.

    With ``settings.guardrails_enabled``:
      - Runs through ``GuardedAgent``; catches ``InputGuardrailViolation`` /
        ``OutputGuardrailViolation`` and returns a safe-refusal turn.
    Without ``settings.guardrails_enabled``:
      - Runs through the plain orchestrator; ``guardrails`` fields default to empty.

    Model errors (``ModelHTTPError`` / ``UnexpectedModelBehavior`` /
    ``UsageLimitExceeded``) are caught and degraded gracefully — never a 500.

    req: multilingual-001, multilingual-004, guardrails-001, guardrails-012,
         guardrails-013, guardrails-016, orchestrator-and-fusion-002, -013
    """
    usage = RunUsage()
    geo: GeoContext = GeoContext()
    active_lang = decision.active_lang

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
            geo = await GeoFusionService(http, settings).resolve(request_ip)
            deps = _build_agent_deps(db, http, session_id, request_ip, decision, det, geo)

            if settings.guardrails_enabled:
                with logfire.span("guardrails.run"):
                    try:
                        result = await get_guarded_orchestrator().run(
                            message,
                            deps=deps,
                            message_history=history,
                            usage=usage,
                            usage_limits=UsageLimits(
                                request_limit=6,
                                tool_calls_limit=8,
                                total_tokens_limit=20_000,
                            ),
                        )
                    except InputGuardrailViolation as exc:
                        # Input guard fired — no model call was made.
                        # req: guardrails-003, guardrails-004, guardrails-005,
                        #      guardrails-006, guardrails-010, guardrails-012
                        in_names = [input_name(exc.guardrail_name)]
                        await _persist_language_state(repo, session, db, decision, settings)
                        await db.commit()
                        return _build_block_turn(active_lang, det, in_names=in_names)
                    except OutputGuardrailViolation as exc:
                        # Output guard fired after model ran — replace reply with refusal.
                        # req: guardrails-008, guardrails-009, guardrails-010, guardrails-012
                        out_names = [output_name(exc.guardrail_name)]
                        await _persist_language_state(repo, session, db, decision, settings)
                        await db.commit()
                        return _build_block_turn(
                            active_lang,
                            det,
                            out_names=out_names,
                            geo_country=geo.country,
                        )
            else:
                # guardrails_enabled=False → plain orchestrator; no guardrail checks.
                # req: guardrails-016
                result = await get_orchestrator().run(
                    message,
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
        log.warning(
            "Orchestrator error — degrading turn (session=%r): %s: %s",
            session_id,
            type(exc).__name__,
            exc,
        )
        await _persist_language_state(repo, session, db, decision, settings)
        await db.commit()
        turn = degraded_turn(active_lang)
        turn.detected_country = geo.country  # req: orchestrator-and-fusion-013
        return turn

    await _persist_language_state(repo, session, db, decision, settings)
    await repo.save_messages(session_id, result.all_messages())
    await db.commit()
    out: TurnOutput = result.output
    return out


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=TurnOutput)
async def chat(
    req: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> TurnOutput:
    """Full per-turn pipeline: detect → resolve → guardrailed-agent → persist.

    Never returns a 500 — model errors and guardrail blocks degrade to a safe
    TurnOutput with needs_review=True.

    req: multilingual-001, multilingual-004, multilingual-008, multilingual-009
    req: guardrails-001..010, guardrails-012, guardrails-013, guardrails-016
    """
    settings = get_settings()
    with logfire.span("chat_turn", session_id=req.session_id):
        pipeline = LanguagePipeline(settings)
        det = _detect_language(req.message, pipeline)

        repo = SessionRepository(db)
        session = await repo.get_or_create(req.session_id)
        decision = pipeline.resolve(session, det)

        request_ip: str = request.client.host if request.client else "unknown"
        history = await repo.load_messages(req.session_id)

        turn = await _run_turn(
            db=db,
            repo=repo,
            session=session,
            decision=decision,
            det=det,
            session_id=req.session_id,
            request_ip=request_ip,
            message=req.message,
            history=history,
            settings=settings,
        )

        _emit_telemetry(
            req.session_id,
            turn,
            turn.guardrails.input,
            turn.guardrails.output,
        )

        if settings.runtime_eval_enabled and is_goodbye(req.message, decision.active_lang):
            background_tasks.add_task(_background_eval, req.session_id)

        return turn
