"""Guardrails package — deterministic multilingual detectors (ES/EN/PT).

Exposes the public detector API from ``app.guardrails.detectors``.  The engine
(``engine.py``) and refusal strings (``refusal.py``) live in sibling modules written
by other specialists in parallel; they are NOT imported here so this init stays safe
to import independently.

Requirements: guardrails-003..guardrails-010, guardrails-011, guardrails-014
Design: specs/guardrails/design.md §2.1
"""

from app.guardrails.detectors import (
    PiiMatch,
    detect_jailbreak,
    detect_off_topic,
    detect_pii,
    detect_prompt_injection,
    detect_secret_leak,
    detect_toxicity,
    redact_pii,
)

__all__ = [
    "PiiMatch",
    "detect_jailbreak",
    "detect_off_topic",
    "detect_pii",
    "detect_prompt_injection",
    "detect_secret_leak",
    "detect_toxicity",
    "redact_pii",
]
