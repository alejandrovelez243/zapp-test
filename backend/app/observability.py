"""Safe, token-gated observability wiring for the backend.

Owns the telemetry seam — and ONLY the seam. Two complementary backends with a strict,
graded ownership split:

* **Logfire** = engineering observability + LLM tracing. Distributed traces, FastAPI HTTP
  spans (the trace root), outbound ``httpx`` egress (the geo / REST Countries fusion
  calls), SQLAlchemy / pgvector DB spans, and PydanticAI agent/model/tool spans with
  per-call token usage + ``operation.cost``. Logfire scrubs PII by default and is the ONLY
  place student-message CONTENT may land.
* **PostHog** = product analytics (session replay, funnels, dashboards). PostHog does NOT
  scrub PII, so student-message content NEVER goes here — METADATA ONLY. This module only
  constructs the client; no events are emitted in this task.

Region: US (the default Logfire app host and the default PostHog Cloud host) is used for
BOTH backends so they stay consistent; ``Settings`` exposes no host/region override field,
so the SDK defaults (US) apply.

``configure_observability(app)`` is called once from ``app/main.py`` at startup (NOT at
import time, so ``import app.observability`` succeeds with no env set). It is fully
token-gated and never raises: a missing ``logfire_token`` / ``posthog_key`` — or any init
error, including ``Settings`` failing to load because required env is absent — degrades to
a safe no-op so the app always boots.

Requirement: platform-scaffold-013 (safe Logfire/PostHog init; no-op without tokens).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import logfire
from posthog import Posthog

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Service identity reported to Logfire. Kept here (not in the secrets config) because it is
# neither a secret nor a per-env token; tokens/region live in / default from ``Settings``.
_SERVICE_NAME = "zapp-backend"

# Module-level state so callers can no-op safely and re-invocation is idempotent.
_posthog_client: Posthog | None = None
_initialized = False


def get_posthog() -> Posthog | None:
    """Return the process-wide PostHog client, or ``None`` when analytics is disabled.

    Callers MUST treat ``None`` as "analytics off" and skip emission — there is no client
    until :func:`configure_observability` runs with a ``posthog_key`` present. Remember:
    METADATA ONLY (language, country, confidence, flags, scores, latency buckets); student
    message CONTENT belongs in Logfire, never here.
    """
    return _posthog_client


def configure_observability(app: FastAPI) -> None:
    """Wire Logfire + PostHog at startup; no-op (never raise) when tokens/env are absent.

    Called once from ``app/main.py`` (not at import time). Logfire is wired only when
    ``settings.logfire_token`` is set; PostHog only when ``settings.posthog_key`` is set.
    Any failure — missing tokens, ``Settings`` unable to load, or an SDK error — is logged
    at WARNING and swallowed so the application always boots.
    """
    global _initialized
    if _initialized:
        # Idempotent: instrumentation is global; do not double-instrument on re-entry.
        return

    # Ensure app INFO logs (ingest pipeline, etc.) reach stdout (docker/Railway).
    # uvicorn configures its own loggers but not the root, so stdlib app logs would
    # otherwise be invisible. basicConfig is a no-op if the root already has handlers.
    logging.basicConfig(level=logging.INFO)

    # Importing settings can itself raise (required env absent in local/CI/static checks).
    # Treat that exactly like "no tokens" -> safe no-op.
    from app.config import get_settings

    try:
        settings = get_settings()
    except Exception as exc:  # boot must never fail on observability
        logger.warning("Observability disabled: settings unavailable (%s).", exc)
        _initialized = True
        return

    _configure_logfire(app, settings.logfire_token)
    _configure_posthog(settings.posthog_key)
    _initialized = True


def _configure_logfire(app: FastAPI, token: str | None) -> None:
    """Configure Logfire and attach FastAPI/httpx/SQLAlchemy/PydanticAI instrumentation.

    No-op when ``token`` is falsy. The FastAPI span is the trace root; httpx
    ``capture_all=True`` records the fused geo / REST Countries request/response bodies
    (safe because Logfire's default PII scrubbing stays ON); SQLAlchemy is instrumented via
    the async engine's ``sync_engine`` (Logfire instruments the sync engine underneath an
    ``AsyncEngine``); ``instrument_pydantic_ai`` is harmless now and captures future agents.
    """
    if not token:
        return
    try:
        from app.db import get_engine

        logfire.configure(
            token=token,
            service_name=_SERVICE_NAME,
            send_to_logfire="if-token-present",
        )
        logfire.instrument_fastapi(app)
        logfire.instrument_httpx(capture_all=True)
        logfire.instrument_sqlalchemy(engine=get_engine().sync_engine)
        logfire.instrument_pydantic_ai()
        logger.info("Logfire instrumentation enabled.")
    except Exception as exc:  # boot must never fail on observability
        logger.warning("Logfire init failed; continuing without it (%s).", exc)


def _configure_posthog(key: str | None) -> None:
    """Construct the PostHog client (metadata-only product analytics).

    No-op when ``key`` is falsy. ``Settings`` exposes no host/region field, so the SDK's
    default (US Cloud) host applies, matching the Logfire region. ``disable_geoip`` is left
    at the SDK default (on) since no IP-derived data is wanted here.
    """
    global _posthog_client
    if not key:
        return
    try:
        _posthog_client = Posthog(key)
        logger.info("PostHog analytics client initialized.")
    except Exception as exc:  # boot must never fail on observability
        logger.warning("PostHog init failed; continuing without it (%s).", exc)
        _posthog_client = None
