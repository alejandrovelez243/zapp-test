"""POST /chat FastAPI boundary — language detection → guardrails → orchestrator → persistence.

Full pipeline: detect → resolve_active_lang → input guardrails → AgentDeps → orchestrator.run →
output guardrails → persist session + messages → return TurnOutput.  Degrades gracefully on
``ModelHTTPError | UnexpectedModelBehavior | UsageLimitExceeded`` (never returns a 500).

req: multilingual-001, -004, -008, -009; guardrails-001 through -010, -012, -013
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import degraded_turn, get_orchestrator
from app.agents.session import ConversationSession, SessionRepository
from app.config import Settings, get_settings
from app.contract import GuardrailReport, TurnOutput
from app.db import get_session, get_sessionmaker
from app.deps import AgentDeps
from app.eval.runtime import evaluate_conversation
from app.fusion.geo import GeoContext, GeoFusionService
from app.guardrails.engine import GuardrailEngine, GuardrailResult
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


async def _blocked_turn(
    *,
    gr_in: GuardrailResult,
    decision: ActiveLangDecision,
    det: DetectionResult,
    session_id: str,
    repo: SessionRepository,
    session: ConversationSession,
    db: AsyncSession,
    settings: Settings,
) -> TurnOutput:
    """Short-circuit path: persist session state and return a safe refusal without calling the LLM.

    The orchestrator is never reached, so this path works with no gateway key.

    req: guardrails-003, guardrails-004, guardrails-005, guardrails-012, guardrails-013
    """
    await _persist_language_state(repo, session, db, decision, settings)
    await db.commit()

    # Primary category drives the refusal wording; fail-safe to "prompt_injection".
    primary: str = gr_in.triggered[0] if gr_in.triggered else "prompt_injection"
    blocked = TurnOutput(
        reply=safe_refusal(decision.active_lang, primary),
        detected_lang=det.lang or decision.active_lang,
        active_lang=decision.active_lang,
        lang_confidence=0.0,
        final_normalized_text="",
        detected_country=None,
        confidence_score=0.0,
        needs_review=True,
        guardrails=GuardrailReport(input=gr_in.triggered),
    )
    _emit_telemetry(session_id, blocked, gr_in.triggered, [])
    return blocked


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


async def _run_orchestrator_turn(
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
) -> tuple[TurnOutput, bool]:
    """Geo-resolve → build deps → run orchestrator; degrade on model errors.

    Returns ``(turn, session_ended)`` where *session_ended* is ``True`` when the
    ``end_session`` tool fired this turn (the caller schedules ``evaluate_conversation``
    as a background task).  On the degrade path, returns ``(degraded_turn, False)``.

    Also handles the ``switch_language`` signal: if the tool updated
    ``deps.lang_switch_requested`` during the run, an effective decision with the
    new language code is used for session persistence instead of the pre-run decision.

    req: multilingual-001, multilingual-004, multilingual-015, guardrails-006,
         orchestrator-and-fusion-002, orchestrator-and-fusion-013, evaluation-015
    """
    usage = RunUsage()
    geo: GeoContext = GeoContext()
    deps: AgentDeps | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
            geo = await GeoFusionService(http, settings).resolve(request_ip)
            deps = _build_agent_deps(db, http, session_id, request_ip, decision, det, geo)
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
        turn = degraded_turn(decision.active_lang)
        turn.detected_country = geo.country  # req: orchestrator-and-fusion-013
        return turn, False

    # -- switch_language signal: if the tool switched the language, persist the new
    #    active_lang instead of the pre-run state-machine decision.
    #    req: multilingual-015
    assert deps is not None  # always set on the happy path (except returned above)
    if deps.lang_switch_requested is not None:
        effective_decision = ActiveLangDecision(
            active_lang=deps.lang_switch_requested,
            first_turn=decision.first_turn,
            locked=True,
            switched=True,
            pending_switch_lang=None,
            pending_switch_count=0,
        )
    else:
        effective_decision = decision

    await _persist_language_state(repo, session, db, effective_decision, settings)
    await repo.save_messages(session_id, result.all_messages())
    await db.commit()

    # -- end_session signal: return flag so the caller schedules evaluate_conversation.
    #    req: evaluation-015
    return result.output, deps.session_ended


def _apply_output_guardrails(
    turn: TurnOutput,
    engine: GuardrailEngine,
    gr_in: GuardrailResult,
) -> tuple[TurnOutput, GuardrailResult]:
    """Run output guardrails, apply block/redact, and merge names into the contract.

    Modifies *turn* in place (reply replacement / needs_review update) and returns
    the updated turn together with the output GuardrailResult for telemetry.

    req: guardrails-001, guardrails-002, guardrails-008, guardrails-009,
         guardrails-010, guardrails-013
    """
    with logfire.span("guardrails.output"):
        gr_out: GuardrailResult = engine.run_output(turn.reply)

    if gr_out.blocked:
        # Block wins over redact — replace with safe refusal.
        # req: guardrails-009, guardrails-010
        primary_out: str = gr_out.triggered[0] if gr_out.triggered else "secret_leak"
        turn.reply = safe_refusal(turn.active_lang, primary_out)
    elif gr_out.action == "redact":
        # Scrub PII from reply text.  req: guardrails-008
        turn.reply = gr_out.text

    # Merge guardrail names and OR needs_review.  req: guardrails-002
    turn.guardrails = GuardrailReport(input=gr_in.triggered, output=gr_out.triggered)
    turn.needs_review = turn.needs_review or bool(gr_in.triggered or gr_out.triggered)
    return turn, gr_out


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
    """Full per-turn pipeline: detect → resolve → guardrails → agent → guardrails → persist.

    Never returns a 500 — model errors degrade to a safe TurnOutput with needs_review=True.
    req: multilingual-001, multilingual-004, multilingual-008, multilingual-009
    req: guardrails-001..010, guardrails-012, guardrails-013
    """
    settings = get_settings()
    with logfire.span("chat_turn", session_id=req.session_id):
        pipeline = LanguagePipeline(settings)
        det = _detect_language(req.message, pipeline)

        repo = SessionRepository(db)
        session = await repo.get_or_create(req.session_id)
        decision = pipeline.resolve(session, det)

        request_ip: str = request.client.host if request.client else "unknown"

        engine = GuardrailEngine(settings)
        with logfire.span("guardrails.input"):
            gr_in: GuardrailResult = await engine.run_input(req.message, decision.active_lang)

        if gr_in.blocked:
            return await _blocked_turn(
                gr_in=gr_in,
                decision=decision,
                det=det,
                session_id=req.session_id,
                repo=repo,
                session=session,
                db=db,
                settings=settings,
            )

        history = await repo.load_messages(req.session_id)
        turn, session_ended = await _run_orchestrator_turn(
            db=db,
            repo=repo,
            session=session,
            decision=decision,
            det=det,
            session_id=req.session_id,
            request_ip=request_ip,
            message=gr_in.text,
            history=history,
            settings=settings,
        )

        turn, gr_out = _apply_output_guardrails(turn, engine, gr_in)
        _emit_telemetry(req.session_id, turn, gr_in.triggered, gr_out.triggered)

        # req: evaluation-015 — end_session tool replaces the is_goodbye keyword heuristic.
        if settings.runtime_eval_enabled and session_ended:
            background_tasks.add_task(_background_eval, req.session_id)

        return turn
