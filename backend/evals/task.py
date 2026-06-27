"""System-under-test for the pydantic-evals offline suite.

Mirrors the ``/chat`` turn boundary WITHOUT HTTP/DB so ``pydantic-evals`` can call
``run_turn`` per Case: detect language → resolve session language → build AgentDeps →
run the orchestrator → return the nine-field TurnOutput contract dict.

No database writes are performed (``session=None``; the orchestrator has no DB tool in
this release, so the ``AsyncSession`` slot is never accessed at runtime).  A real
Pydantic AI Gateway key (``PYDANTIC_AI_GATEWAY_API_KEY``) is required for a live run;
CI overrides the model with ``TestModel`` to stay key-free.

Design contract: specs/evaluation/design.md §3.2
Requirement: evaluation-001
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import httpx
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import get_orchestrator
from app.agents.session import ConversationSession
from app.config import get_settings
from app.contract import GuardrailReport, TurnOutput
from app.deps import AgentDeps
from app.fusion.geo import GeoContext, GeoFusionService
from app.guardrails.engine import GuardrailEngine
from app.guardrails.refusal import safe_refusal
from app.lang.pipeline import LanguagePipeline
from app.time import now_utc


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

    # Settings resolved once per turn; shared by LanguagePipeline and GuardrailEngine.
    settings = get_settings()

    # Step 1 — Deterministic language detection (lingua; never raises per multilingual-012).
    pipeline = LanguagePipeline(settings)
    det = pipeline.detect(message)

    # Step 2 — Transient ConversationSession (no DB writes; evals never persist state).
    #   created_at / updated_at follow the project's naive-UTC convention.
    now = now_utc()
    session = ConversationSession(
        id=session_id,
        active_lang=prior_active_lang,
        created_at=now,
        updated_at=now,
    )

    # Step 3 — Pure language-state machine: derives the active_lang for this turn.
    decision = pipeline.resolve(session, det)

    # Step 3b — Input guardrails (mirror the /chat boundary). A block short-circuits the
    #   turn WITHOUT a model call; redact forwards a cleaned message; flag carries names.
    engine = GuardrailEngine(settings)
    gr_in = await engine.run_input(message, decision.active_lang)
    if gr_in.blocked:
        primary_in = gr_in.triggered[0] if gr_in.triggered else "default"
        blocked = TurnOutput(
            reply=safe_refusal(decision.active_lang, primary_in),
            detected_lang=det.lang or decision.active_lang,
            active_lang=decision.active_lang,
            lang_confidence=0.0,
            final_normalized_text="",
            detected_country=None,
            confidence_score=0.0,
            needs_review=True,
            guardrails=GuardrailReport(input=gr_in.triggered),
        )
        blocked_out: dict[str, Any] = blocked.model_dump()
        blocked_out["_usage"] = {"input_tokens": 0, "output_tokens": 0}
        return blocked_out

    # The (possibly PII-redacted) message forwarded to the agent.
    agent_message: str = gr_in.text

    http = httpx.AsyncClient()
    try:
        # Step 3c — Geo resolution (mirror /chat boundary).
        # Resolves detected_country / locale / timezone so the orchestrator
        # output_validator (_reconcile_fusion) can set detected_country and
        # confidence_score correctly.  GeoFusionService.resolve NEVER raises
        # (errors → GeoContext(source="error", ok=False)) so no extra guard needed.
        # req: orchestrator-and-fusion-001, orchestrator-and-fusion-002
        #
        # When inputs["geo"] was provided (see _raw_geo above), build GeoContext
        # directly from the injected dict and skip the live ipapi.co call.  This
        # keeps geo-asserting Cases deterministic in CI regardless of ipapi.co
        # availability or rate limits.  When _raw_geo is None, resolve live.
        # req: orchestrator-and-fusion-002, -010, -011
        #
        # Criterion-006 (relative-date resolution) determinism:
        #   The orchestrator's _with_geo_context instruction injects "now" at run time,
        #   so the absolute date in final_normalized_text is non-deterministic across
        #   wall-clock calls.  For eval criterion-006 Cases, assert that an absolute
        #   date APPEARS in final_normalized_text (normalization occurred) rather than
        #   asserting an exact value — OR inject a fixed "now" via a settings/env
        #   override before calling run_turn.  Do NOT over-engineer run_turn for this;
        #   geo resolution here is sufficient.
        #   req: orchestrator-and-fusion-006
        if _raw_geo is not None:
            geo = GeoContext.model_validate(_raw_geo)
        else:
            geo = await GeoFusionService(http, settings).resolve(request_ip)

        # Step 4 — Build AgentDeps.
        #   ``session=None`` is intentional: the orchestrator has no DB tool in this release,
        #   so the AsyncSession slot is never accessed during the run.  ``cast`` satisfies
        #   strict mypy without runtime overhead; a type-ignore comment would be equivalent
        #   but less expressive.
        deps = AgentDeps(
            session=cast(AsyncSession, None),
            http=http,
            session_id=session_id,
            request_ip=request_ip,
            active_lang=decision.active_lang,
            detection=det,
            lang_decision=decision,
            geo=geo,
        )

        # Step 5 — RunUsage accumulates tokens across the full run (tools + retries +
        #   output validators).  Passed as ``usage=`` so the agent appends into it.
        #   Attr names confirmed via: RunUsage().__dict__ / dir(RunUsage()).
        #   Relevant attrs: input_tokens, output_tokens (both int, 0 when unused).
        usage = RunUsage()

        # Step 6 — Orchestrator run.
        #   When PYDANTIC_AI_GATEWAY_API_KEY is set, a real gateway call is made.
        #   In CI, override the model before calling run_turn:
        #     with get_orchestrator().override(model=TestModel(...)): ...
        result = await get_orchestrator().run(agent_message, deps=deps, usage=usage)

        # Step 7 — Output guardrails (mirror /chat): block/redact the reply, then populate
        #   the guardrails contract field + needs_review from both input and output hits.
        turn = result.output
        gr_out = engine.run_output(turn.reply)
        if gr_out.blocked:
            primary_out = gr_out.triggered[0] if gr_out.triggered else "default"
            turn.reply = safe_refusal(turn.active_lang, primary_out)
        elif gr_out.action == "redact":
            turn.reply = gr_out.text
        turn.guardrails = GuardrailReport(input=gr_in.triggered, output=gr_out.triggered)
        turn.needs_review = turn.needs_review or bool(gr_in.triggered or gr_out.triggered)

        # Step 8 — Serialise the nine-field contract and attach private usage metadata.
        #   The ``_usage`` key is not part of the TurnOutput schema; evaluators read it
        #   from the returned dict to compute cost and latency.
        out: dict[str, Any] = turn.model_dump()
        out["_usage"] = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        return out

    finally:
        # Always close the httpx client — even when the orchestrator raises.
        await http.aclose()
