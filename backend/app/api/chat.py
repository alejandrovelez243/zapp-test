"""Scaffold ``POST /chat`` stub — returns a type-valid ``TurnOutput`` placeholder.

This is intentionally a *stub*: it makes NO LLM call and constructs NO PydanticAI
agent. It exists so the API surface and the per-turn JSON contract are live and
testable before the conversational pipeline lands. Because nothing is actually
reasoned about, the placeholder is honest about it: ``needs_review=True`` and a
``confidence_score`` of ``0.0``. The router is mounted in ``app/main.py`` in a
later task.

Requirements:
- platform-scaffold-009 (``POST /chat`` returns a valid ``TurnOutput``).
- platform-scaffold-010 (stub returns ``needs_review=true`` + fixed reply, no LLM).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.contract import GuardrailReport, TurnOutput

router = APIRouter()

_PLACEHOLDER_REPLY = "(placeholder) scaffold is live; conversational features not yet implemented."


class ChatRequest(BaseModel):
    """Inbound chat turn payload."""

    session_id: str
    message: str


@router.post("/chat", response_model=TurnOutput)
async def chat(request: ChatRequest) -> TurnOutput:
    """Return a fixed, type-valid ``TurnOutput`` placeholder — no LLM call."""
    return TurnOutput(
        reply=_PLACEHOLDER_REPLY,
        detected_lang="en",
        active_lang="en",
        lang_confidence=0.0,
        final_normalized_text="",
        detected_country=None,
        confidence_score=0.0,
        needs_review=True,
        guardrails=GuardrailReport(),
    )
