"""Typed dependency container for the PydanticAI orchestrator (request-scoped).

``AgentDeps`` is the single object carried via ``RunContext[AgentDeps]`` into the
orchestrator and its tools (dependency injection only — never module globals). It bundles
the async DB session, the shared ``httpx`` client (so outbound geo/locale calls land in
one Logfire span), and per-request signals (session id, request IP, locked language, admin
token). No PydanticAI agent is constructed in this feature; this is the seam others build
on, unused by the ``/chat`` stub.

Requirement: platform-scaffold-012 (define ``AgentDeps`` alongside the single config
module).
"""

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AgentDeps:
    """Request-scoped dependencies injected into every agent run via ``RunContext``."""

    session: AsyncSession
    http: httpx.AsyncClient
    session_id: str
    request_ip: str
    active_lang: str
    admin_token: str | None = None
