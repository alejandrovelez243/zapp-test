"""POST /chat FastAPI boundary — language detection → orchestrator → session persistence.

Wires the full per-turn pipeline:
  detect → resolve_active_lang → build AgentDeps → orchestrator.run →
  persist session + messages → return TurnOutput.

Catches ``ModelHTTPError | UnexpectedModelBehavior | UsageLimitExceeded`` and degrades
gracefully (never returns a 500 for model errors).

Requirements satisfied:
  multilingual-001 — emit the full nine-field TurnOutput on every /chat turn
  multilingual-004 — first-turn active_lang lock persisted via update_session
  multilingual-008 — locked + unsupported → keep active_lang, still persisted
  multilingual-009 — first-turn unsupported → fallback "en", session persisted

Design contract: specs/multilingual/design.md §2.6
"""

import logging

import httpx
from fastapi import APIRouter, Depends, Request
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
from app.contract import TurnOutput
from app.db import get_session
from app.deps import AgentDeps
from app.lang.detector import LanguageDetector
from app.lang.state import resolve_active_lang

log = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    """Inbound chat turn payload."""

    session_id: str
    message: str


@router.post("/chat", response_model=TurnOutput)
async def chat(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> TurnOutput:
    """Full chat turn: detect → resolve → run agent → persist → return TurnOutput.

    Never returns a 500: ``ModelHTTPError``, ``UnexpectedModelBehavior``, and
    ``UsageLimitExceeded`` are caught and degrade to a safe ``TurnOutput`` with
    ``needs_review=True``.  Session language state is always persisted even on
    the degrade path so subsequent turns remain coherent.

    req: multilingual-001, multilingual-004, multilingual-008, multilingual-009
    """
    settings = get_settings()

    # 1. Deterministic language detection (pre-agent, no LLM round-trip).
    #    req: multilingual-002
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

    # 5. Load message history for session coherence.
    #    req: multilingual-007
    history = await load_messages(db, req.session_id)

    # 6. Run the orchestrator inside a per-request httpx client so every outbound
    #    geo/locale call in the agent run (future orchestrator-and-fusion tasks) is
    #    captured in one Logfire span via logfire.instrument_httpx(capture_all=True).
    #    req: multilingual-001
    usage = RunUsage()
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
                req.message,
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
        return degraded_turn(decision.active_lang)

    # 7. Persist language state + full message history.
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

    # 8. Return the structured output emitted by the orchestrator output_validator.
    #    req: multilingual-001
    return result.output
