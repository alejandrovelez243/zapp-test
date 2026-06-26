"""Typed dependency container for the PydanticAI orchestrator (request-scoped).

``AgentDeps`` is the single object carried via ``RunContext[AgentDeps]`` into the
orchestrator and its tools (dependency injection only — never module globals). It bundles
the async DB session, the shared ``httpx`` client (so outbound geo/locale calls land in
one Logfire span), and per-request signals (session id, request IP, locked language, admin
token). It also carries the two pre-agent language signals the orchestrator's
output_validator reconciles: the deterministic ``DetectionResult`` and the
``ActiveLangDecision`` from the state machine.

Requirements:
  platform-scaffold-012 — define ``AgentDeps`` alongside the single config module.
  multilingual-005/-007/-012 — carry ``detection`` + ``lang_decision`` so the
  orchestrator output_validator can fuse signals and set ``needs_review``.
"""

from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.fusion.geo import GeoContext
from app.lang.detector import DetectionResult
from app.lang.state import ActiveLangDecision


def _default_detection() -> DetectionResult:
    """Safe placeholder detection (detector-not-run) for stub/test constructions.

    Represents "no detector signal yet"; the ``/chat`` boundary (Task 9) replaces it
    with the real ``DetectionResult`` before the orchestrator runs.
    """
    return DetectionResult(lang=None, confidence=0.0, is_reliable=False)


def _default_lang_decision() -> ActiveLangDecision:
    """Safe placeholder language decision for stub/test constructions.

    A pre-lock decision over the configured fallback language; the ``/chat`` boundary
    (Task 9) replaces it with the real ``resolve_active_lang(...)`` output.
    """
    return ActiveLangDecision(active_lang="en", first_turn=True, locked=False)


@dataclass
class AgentDeps:
    """Request-scoped dependencies injected into every agent run via ``RunContext``."""

    session: AsyncSession
    http: httpx.AsyncClient
    session_id: str
    request_ip: str
    active_lang: str
    admin_token: str | None = None
    # Language signals reconciled by the orchestrator output_validator (multilingual).
    # Defaulted so existing stub constructions keep working; the /chat boundary (Task 9)
    # sets the real values from the detector + state machine.
    detection: DetectionResult = field(default_factory=_default_detection)
    lang_decision: ActiveLangDecision = field(default_factory=_default_lang_decision)
    # req: orchestrator-and-fusion-001 — carry resolved geo into every agent run.
    # Defaulted so existing AgentDeps() construction sites keep working without
    # passing geo; the /chat boundary (Task 6) sets the real GeoContext.
    geo: GeoContext = field(default_factory=GeoContext)
