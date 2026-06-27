"""Guardrails package — pydantic-ai-guardrails framework integration.

The hand-rolled detectors/engine/llm modules have been replaced by the
``pydantic-ai-guardrails`` ``GuardedAgent`` framework (see ``get_guarded_orchestrator``
in ``app/agents/orchestrator.py``).

This package now exposes:
  - ``safe_refusal`` — multilingual on-brand refusal strings (ES/EN/PT).
  - ``adapter`` — name-mapping from framework guard names → contract vocabulary.

Requirements: guardrails-001..019
Design: specs/guardrails/design.md
"""

from app.guardrails.refusal import safe_refusal

__all__ = [
    "safe_refusal",
]
