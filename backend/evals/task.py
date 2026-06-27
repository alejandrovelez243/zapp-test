"""System-under-test for the pydantic-evals offline suite.

Mirrors the ``/chat`` turn boundary WITHOUT HTTP/DB so ``pydantic-evals`` can call
``run_turn`` per Case: detect language → resolve session language → build AgentDeps →
run the (guarded or plain) orchestrator → return the nine-field TurnOutput contract dict.

No database writes are performed (``session=None``; the orchestrator has no DB tool in
this release, so the ``AsyncSession`` slot is never accessed at runtime).  A real
Pydantic AI Gateway key (``PYDANTIC_AI_GATEWAY_API_KEY``) is required for a live run;
CI overrides the model with ``TestModel`` to stay key-free.

Design contract: specs/evaluation/design.md §3.2
Requirement: evaluation-001
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from pydantic_ai.usage import RunUsage
from pydantic_ai_guardrails import InputGuardrailViolation, OutputGuardrailViolation
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import get_guarded_orchestrator, get_orchestrator
from app.agents.session import ConversationSession
from app.config import get_settings
from app.contract import GuardrailReport, TurnOutput
from app.deps import AgentDeps
from app.fusion.geo import GeoContext, GeoFusionService
from app.guardrails.adapter import category_for, input_name, output_name
from app.guardrails.refusal import safe_refusal
from app.lang.pipeline import LanguagePipeline


def _now_utc() -> datetime:
    """Return the current naive-UTC datetime (matches project timestamp convention).

    Strips ``tzinfo`` to match the ``TIMESTAMP WITHOUT TIME ZONE`` columns used by
    the project — Postgres rejects timezone-aware datetimes for those columns.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _build_blocked_output(
    message: str,
    active_lang: str,
    det_lang: str | None,
    *,
    in_names: list[str] | None = None,
    out_names: list[str] | None = None,
) -> dict[str, Any]:
    """Build the nine-field TurnOutput dict for a guardrail-block path.

    Used for both input-side blocks (no model call) and output-side blocks
    (model ran, reply replaced).  Mirrors the /chat boundary behavior.

    req: guardrails-003, guardrails-004, guardrails-005, guardrails-006,
         guardrails-008, guardrails-009, guardrails-010, guardrails-012
    """
    all_names = (in_names or []) + (out_names or [])
    primary = category_for(all_names)
    blocked = TurnOutput(
        reply=safe_refusal(active_lang, primary),
        detected_lang=det_lang or active_lang,
        active_lang=active_lang,
        lang_confidence=0.0,
        final_normalized_text="",
        detected_country=None,
        confidence_score=0.0,
        needs_review=True,
        guardrails=GuardrailReport(
            input=in_names or [],
            output=out_names or [],
        ),
    )
    out: dict[str, Any] = blocked.model_dump()
    out["_usage"] = {"input_tokens": 0, "output_tokens": 0}
    return out


async def run_turn(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run one orchestrator turn and return the TurnOutput contract dict.

    Called by ``pydantic-evals`` ``Dataset.evaluate_sync(run_turn)`` for each Case.
    Mirrors the ``/chat`` endpoint's pre-run setup (detection → language resolution →
    AgentDeps) without any HTTP or database I/O.

    Parameters
    ----------
    inputs:
        ``message``           (str)       — the user's raw message text.
        ``ip``                (str)       — caller IP used for geo-signal enrichment;
                                            defaults to ``"0.0.0.0"`` when absent.
        ``prior_active_lang`` (str|None)  — ISO 639-1 code the session was locked to on
                                            prior turns; ``None`` on the first turn.
        ``session_id``        (str|None)  — externally supplied session id; a UUID v4 is
                                            generated when absent or empty.

    Returns
    -------
    dict[str, Any]
        The nine-field ``TurnOutput`` serialised by ``model_dump()``, plus a private
        ``_usage`` key that stores per-run token counts for cost/latency evaluators::

            {
              "reply": "...",
              "detected_lang": "es",
              "active_lang": "es",
              "lang_confidence": 0.95,
              "final_normalized_text": "...",
              "detected_country": None,
              "confidence_score": 0.9,
              "needs_review": False,
              "guardrails": {"input": [], "output": []},
              "_usage": {"input_tokens": 120, "output_tokens": 80},
            }
    """
    message: str = inputs["message"]
    request_ip: str = inputs.get("ip", "0.0.0.0")
    prior_active_lang: str | None = inputs.get("prior_active_lang")
    session_id: str = inputs.get("session_id") or str(uuid.uuid4())
    # Optional geo injection: when inputs["geo"] is provided as a dict, a
    # GeoContext is built from it directly and the live GeoFusionService.resolve
    # call is skipped.  This decouples geo-assertion Cases from ipapi.co uptime
    # and rate limits, making the eval deterministic for CI.  When absent,
    # resolve live as today.  req: orchestrator-and-fusion-002, -010, -011
    _raw_geo = inputs.get("geo")

    # Settings resolved once per turn; shared by LanguagePipeline.
    settings = get_settings()

    # Step 1 — Deterministic language detection (lingua; never raises per multilingual-012).
    pipeline = LanguagePipeline(settings)
    det = pipeline.detect(message)

    # Step 2 — Transient ConversationSession (no DB writes; evals never persist state).
    #   created_at / updated_at follow the project's naive-UTC convention.
    now = _now_utc()
    session = ConversationSession(
        id=session_id,
        active_lang=prior_active_lang,
        created_at=now,
        updated_at=now,
    )

    # Step 3 — Pure language-state machine: derives the active_lang for this turn.
    decision = pipeline.resolve(session, det)
    active_lang = decision.active_lang

    http = httpx.AsyncClient()
    try:
        # Step 3b — Geo resolution (mirror /chat boundary).
        if _raw_geo is not None:
            geo = GeoContext.model_validate(_raw_geo)
        else:
            geo = await GeoFusionService(http, settings).resolve(request_ip)

        # Step 4 — Build AgentDeps.
        deps = AgentDeps(
            session=cast(AsyncSession, None),
            http=http,
            session_id=session_id,
            request_ip=request_ip,
            active_lang=active_lang,
            detection=det,
            lang_decision=decision,
            geo=geo,
        )

        # Step 5 — RunUsage accumulates tokens across the full run.
        usage = RunUsage()

        # Step 6 — Orchestrator run (guarded or plain, mirrors /chat boundary).
        # req: guardrails-001, guardrails-003..010, guardrails-016
        if settings.guardrails_enabled:
            try:
                result = await get_guarded_orchestrator().run(message, deps=deps, usage=usage)
            except InputGuardrailViolation as exc:
                # Input guardrail fired — no model call was made.
                # req: guardrails-003, guardrails-004, guardrails-005,
                #      guardrails-006, guardrails-010, guardrails-012
                in_names = [input_name(exc.guardrail_name)]
                return _build_blocked_output(message, active_lang, det.lang, in_names=in_names)
            except OutputGuardrailViolation as exc:
                # Output guardrail fired after model ran.
                # req: guardrails-008, guardrails-009, guardrails-010, guardrails-012
                out_names = [output_name(exc.guardrail_name)]
                return _build_blocked_output(message, active_lang, det.lang, out_names=out_names)
        else:
            # guardrails_enabled=False → plain orchestrator.
            # req: guardrails-016
            result = await get_orchestrator().run(message, deps=deps, usage=usage)

        # Step 7 — Serialise the nine-field contract and attach private usage metadata.
        turn = result.output
        out: dict[str, Any] = turn.model_dump()
        out["_usage"] = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        return out

    finally:
        # Always close the httpx client — even when the orchestrator raises.
        await http.aclose()
