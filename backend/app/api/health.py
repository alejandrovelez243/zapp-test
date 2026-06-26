"""Shallow liveness probe — ``GET /health``.

Deliberately a *shallow* check: it performs NO database ping so the endpoint is green
before migrations have run (compose/CI boot order depends on this — the backend is
considered up the moment the process serves, independent of DB readiness). The router is
mounted in ``app/main.py`` in a later task.

Requirement: platform-scaffold-008 (``GET /health`` returns 200 ``{"status": "ok"}``).
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthStatus(BaseModel):
    """Liveness payload — ``status`` is fixed to ``"ok"`` while the process serves."""

    status: Literal["ok"] = "ok"


@router.get("/health")
async def health() -> HealthStatus:
    """Return ``200 {"status": "ok"}`` without touching the database."""
    return HealthStatus()
