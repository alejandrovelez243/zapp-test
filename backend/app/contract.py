"""Canonical per-turn JSON contract (verbatim from the ``json-contract`` skill).

This is the single source of truth for the shape every ``/chat`` turn returns. It is
later set as the PydanticAI orchestrator ``output_type``; for now the ``/chat`` stub
emits a type-valid placeholder. The nine fields, names, and constraints are
non-negotiable — do not add, rename, or drop fields.

Requirement: platform-scaffold-011 (define the canonical ``TurnOutput`` and
``GuardrailReport`` Pydantic models exactly per the constitution's per-turn JSON
contract).
"""

from pydantic import BaseModel, Field
from pydantic_extra_types.country import CountryAlpha2  # ISO 3166-1 alpha-2


class GuardrailReport(BaseModel):
    """Names of guardrails that triggered this turn (empty when clean)."""

    input: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)


class TurnOutput(BaseModel):
    reply: str = Field(..., description="User-facing answer, in active_lang")
    detected_lang: str = Field(
        ..., min_length=2, max_length=2, description="ISO 639-1 the user wrote in"
    )
    active_lang: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Language the session is locked to (es|en|pt or fallback)",
    )
    lang_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Agreement score: LLM detected_lang vs lingua detector"
    )
    final_normalized_text: str = Field(
        ..., description="LLM-cleaned user text fused with resolved locale"
    )
    detected_country: CountryAlpha2 | None = Field(
        default=None, description="Fused geo-IP signal (ISO 3166-1 alpha-2)"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Combined reconciliation confidence"
    )
    needs_review: bool = Field(
        default=False, description="True on low confidence / divergence / caught errors"
    )
    guardrails: GuardrailReport = Field(default_factory=GuardrailReport)
