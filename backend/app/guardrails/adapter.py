"""Adapter: pydantic-ai-guardrails violations → TurnOutput contract names.

Maps the framework's internal guardrail names to the contract vocabulary used in
TurnOutput.guardrails.{input,output} and the adversarial eval's must_trip labels.

Also provides custom InputGuardrail/OutputGuardrail factory functions for cases
where the built-in package guards need to be adapted to our TurnOutput output_type
(output guards) or where the package lacks input-side coverage (secret detection).

Custom output guards extract ``output.reply`` before passing to pattern checks,
which is necessary because our agent has ``output_type=TurnOutput`` (not ``str``).

req: guardrails-002, guardrails-017, guardrails-019
Design: specs/guardrails/design.md §2.2
"""

from __future__ import annotations

import re
from typing import Any

from pydantic_ai_guardrails import (
    GuardrailContext,
    GuardrailResult,
    InputGuardrail,
    OutputGuardrail,
)
from pydantic_ai_guardrails.guardrails.output import toxicity_filter

__all__ = [
    "category_for",
    "input_name",
    "output_name",
    "pii_output_guard",
    "secret_input_guard",
    "secret_output_guard",
    "toxicity_output_guard",
]

# ---------------------------------------------------------------------------
# Name maps: package guardrail name → contract vocabulary
# req: guardrails-002, guardrails-017
# ---------------------------------------------------------------------------

_INPUT_NAME_MAP: dict[str, str] = {
    "prompt_injection": "prompt_injection",
    "pii_detector": "pii_detector",
    "toxicity_detector": "toxicity",
    "secret_input": "secret_leak",
    "guardrail_error": "guardrail_error",
}

_OUTPUT_NAME_MAP: dict[str, str] = {
    "toxicity_output": "toxicity",
    "secret_output": "secret_leak",
    "pii_output": "pii_leak",
    "guardrail_error": "guardrail_error",
}

# Refusal category priority (highest-severity first).
# req: guardrails-019 (fail-safe → "guardrail_error" triggers a block + safe refusal)
_CATEGORY_PRIORITY: list[str] = [
    "prompt_injection",
    "jailbreak",
    "toxicity",
    "secret_leak",
    "pii_detector",
    "pii_leak",
    "off_topic",
    "guardrail_error",
]


def input_name(guard_name: str) -> str:
    """Map a package input-guard name to the contract vocabulary.

    Unknown names are passed through unchanged (fail-open for unknown names).
    req: guardrails-002, guardrails-017
    """
    return _INPUT_NAME_MAP.get(guard_name, guard_name)


def output_name(guard_name: str) -> str:
    """Map a package output-guard name to the contract vocabulary.

    Unknown names are passed through unchanged (fail-open for unknown names).
    req: guardrails-002, guardrails-017
    """
    return _OUTPUT_NAME_MAP.get(guard_name, guard_name)


def category_for(names: list[str]) -> str:
    """Return the highest-priority refusal category from ``names``.

    Used to pick the safe_refusal wording that best matches what fired.
    Falls back to ``"prompt_injection"`` (hardest blocker) when names is empty.

    req: guardrails-019 (fail-safe: empty → generic block with known category)
    """
    for candidate in _CATEGORY_PRIORITY:
        if candidate in names:
            return candidate
    return names[0] if names else "prompt_injection"


# ---------------------------------------------------------------------------
# Fail-safe result — returned when a guard function raises unexpectedly.
# req: guardrails-019
# ---------------------------------------------------------------------------

_FAIL_SAFE_RESULT: GuardrailResult = {
    "tripwire_triggered": True,
    "message": "Guardrail check failed — treating as block (fail-safe).",
    "severity": "critical",
    "metadata": {"action": "fail_safe"},
}

# ---------------------------------------------------------------------------
# Null context — used when delegating to built-in output guards on reply str.
# The inner functions of built-in guards don't use the context, so None is safe.
# ---------------------------------------------------------------------------

_NULL_CTX: GuardrailContext[None] = GuardrailContext(deps=None)

# ---------------------------------------------------------------------------
# Custom input guard: secret detection (package has no input secret guard)
# req: guardrails-010 (input-side), guardrails-019
# ---------------------------------------------------------------------------

_INPUT_SECRET_PATS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"pylf_v\d+_[A-Za-z0-9_]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
]


async def _secret_input_fn(prompt: Any) -> GuardrailResult:
    """Detect API keys / JWT tokens in the user's prompt.

    req: guardrails-010 (input-side secret detection)
    req: guardrails-019 (try/except → fail-safe block on error)
    """
    try:
        text: str = prompt if isinstance(prompt, str) else str(prompt)
        for pat in _INPUT_SECRET_PATS:
            if pat.search(text):
                return {
                    "tripwire_triggered": True,
                    "message": "Potential secret detected in user input.",
                    "severity": "critical",
                }
        return {"tripwire_triggered": False}
    except Exception:  # pragma: no cover  # req: guardrails-019
        return _FAIL_SAFE_RESULT


def secret_input_guard() -> InputGuardrail[None, Any]:
    """Factory: input guardrail that blocks messages containing API keys.

    req: guardrails-010, guardrails-019
    """
    return InputGuardrail(_secret_input_fn, name="secret_input")


# ---------------------------------------------------------------------------
# Custom output guards: extract output.reply for TurnOutput compatibility.
#
# The built-in package output guards expect ``str`` output, but our orchestrator
# has output_type=TurnOutput.  These thin wrappers extract output.reply and
# delegate to built-in guards or inline pattern checks.
# req: guardrails-008, guardrails-009, guardrails-010, guardrails-019
# ---------------------------------------------------------------------------

# Singleton: build the built-in toxicity guard once; reuse across calls.
_INNER_TOXICITY: OutputGuardrail[None, str, Any] = toxicity_filter()


def _reply_str(output: Any) -> str:
    """Extract the reply string from a TurnOutput or fall back to str()."""
    return output.reply if hasattr(output, "reply") else str(output)


async def _toxicity_output_fn(output: Any) -> GuardrailResult:
    """Check output.reply for toxic content via the built-in toxicity_filter.

    req: guardrails-009, guardrails-019
    """
    try:
        reply = _reply_str(output)
        return await _INNER_TOXICITY.validate(reply, _NULL_CTX)
    except Exception:  # pragma: no cover  # req: guardrails-019
        return _FAIL_SAFE_RESULT


def toxicity_output_guard() -> OutputGuardrail[None, Any, Any]:
    """Factory: output guardrail that blocks toxic model replies.

    req: guardrails-009, guardrails-019
    """
    return OutputGuardrail(_toxicity_output_fn, name="toxicity_output")


# Secret patterns for output — mirrors detectors._api_key_re + _prompt_fragment_re.
# These patterns must be kept in sync with the adversarial eval must_trip dataset.
# req: guardrails-010, guardrails-017
_OUTPUT_SECRET_PATS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"pylf_v\d+_[A-Za-z0-9_]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    re.compile(r"-----BEGIN\s+(?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(
        r"(?:my|your|the)\s+(?:system\s+)?(?:instructions?\s+(?:are|say|tell\s+me)"
        r"|prompt\s+(?:is|says))\s*:",
        re.IGNORECASE,
    ),
    re.compile(r"you\s+are\s+(?:zapp|a\s+philosophy\s+school\s+assistant)", re.IGNORECASE),
    re.compile(r"i\s+(?:am|was)\s+(?:instructed|told|programmed)\s+to\b", re.IGNORECASE),
    re.compile(r"(?:my|the)\s+context\s+(?:is|window\s+(?:is|contains))\s*:", re.IGNORECASE),
    re.compile(r"(?:begin|start)\s+of\s+system\s+prompt", re.IGNORECASE),
]


async def _secret_output_fn(output: Any) -> GuardrailResult:
    """Check output.reply for API keys or system-prompt fragments.

    req: guardrails-010, guardrails-019
    """
    try:
        reply = _reply_str(output)
        for pat in _OUTPUT_SECRET_PATS:
            if pat.search(reply):
                return {
                    "tripwire_triggered": True,
                    "message": "Potential secret or system-prompt fragment in model output.",
                    "severity": "critical",
                }
        return {"tripwire_triggered": False}
    except Exception:  # pragma: no cover  # req: guardrails-019
        return _FAIL_SAFE_RESULT


def secret_output_guard() -> OutputGuardrail[None, Any, Any]:
    """Factory: output guardrail that blocks replies containing secrets.

    req: guardrails-010, guardrails-019
    """
    return OutputGuardrail(_secret_output_fn, name="secret_output")


# PII patterns for output (email, phone, SSN, credit card).
# req: guardrails-008
_OUTPUT_PII_PATS: list[re.Pattern[str]] = [
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
]


async def _pii_output_fn(output: Any) -> GuardrailResult:
    """Check output.reply for PII (email, phone, SSN, credit card).

    req: guardrails-008, guardrails-019
    """
    try:
        reply = _reply_str(output)
        for pat in _OUTPUT_PII_PATS:
            if pat.search(reply):
                return {
                    "tripwire_triggered": True,
                    "message": "PII detected in model output.",
                    "severity": "high",
                }
        return {"tripwire_triggered": False}
    except Exception:  # pragma: no cover  # req: guardrails-019
        return _FAIL_SAFE_RESULT


def pii_output_guard() -> OutputGuardrail[None, Any, Any]:
    """Factory: output guardrail that blocks PII in model replies.

    req: guardrails-008, guardrails-019
    """
    return OutputGuardrail(_pii_output_fn, name="pii_output")
