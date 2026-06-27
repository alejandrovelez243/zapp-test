"""Guardrail engine — input/output policy gate for every ``/chat`` turn.

``GuardrailEngine.run_input`` runs before the model (block/redact/flag);
``GuardrailEngine.run_output`` runs after (block/redact).  ``GuardrailResult`` is the
shared data contract.  Injected with compiled ``Detectors`` + ``Settings`` at construction.

req: guardrails-003, -004, -005, -006, -007, -008, -009, -010, -016, -019
Design: specs/guardrails/design.md §2.2 + §4
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from app.config import Settings
from app.guardrails.detectors import Detectors, PiiMatch
from app.guardrails.llm import classify_input

__all__ = ["GuardrailEngine", "GuardrailResult"]

# Name appended to ``triggered`` when a security-critical detector raises unexpectedly.
# Signals an infrastructure error (not a content policy hit) while still causing a block.
# req: guardrails-019
_GUARDRAIL_ERROR_MARKER: str = "guardrail_error"


# ---------------------------------------------------------------------------
# Data model — §4 of the design
# ---------------------------------------------------------------------------


class GuardrailResult(BaseModel):
    """Result returned by :meth:`GuardrailEngine.run_input` / :meth:`GuardrailEngine.run_output`.

    Attributes:
        triggered: Names of all guardrails that fired.  Names MUST match the eval
                   adversarial ``must_trip`` labels (guardrails-017).
        action:    Highest-priority action: ``"clean"`` | ``"block"`` |
                   ``"redact"`` | ``"flag"``.
        text:      The (possibly redacted) text to forward to the model, or ``""``
                   when blocked.  For output guardrails, this is the (possibly redacted)
                   reply.
        blocked:   Convenience flag; ``True`` iff ``action == "block"``.
    """

    triggered: list[str] = []
    action: Literal["clean", "block", "redact", "flag"] = "clean"
    text: str = ""
    blocked: bool = False


# ---------------------------------------------------------------------------
# GuardrailEngine
# ---------------------------------------------------------------------------


class GuardrailEngine:
    """Stateful guardrail engine that owns a :class:`Detectors` instance and settings.

    Construct once per turn (cheap — ``Detectors`` is passed in, not re-compiled) and
    call :meth:`run_input` before the agent, :meth:`run_output` after.

    Args:
        settings:  Application settings for this turn (guardrails_enabled,
                   guardrails_llm_enabled, supported langs, etc.).
        detectors: Pre-built :class:`Detectors` instance.  When ``None`` (the default),
                   a fresh instance is constructed.  Inject a custom instance in tests
                   to simulate detector failures without monkeypatching globals.

    req: guardrails-003..010, guardrails-016, guardrails-019
    """

    def __init__(
        self,
        settings: Settings,
        detectors: Detectors | None = None,
    ) -> None:
        self._settings = settings
        self._detectors: Detectors = detectors if detectors is not None else Detectors()

    # ---------------------------------------------------------------------- #
    # Internal helper — fail-safe wrapper (guardrails-019)
    # ---------------------------------------------------------------------- #

    def _detect_safe(
        self,
        name: str,
        fn: Callable[[], bool],
        triggered: list[str],
    ) -> bool:
        """Run *fn*; on exception append the error marker and return ``True`` (fail-safe).

        Security-critical input detectors (prompt_injection, jailbreak, toxicity) are
        wrapped here so any unexpected exception causes a block rather than letting the
        turn proceed unchecked.  In practice, detectors are written to never raise, but
        this layer ensures the invariant is enforced structurally.

        Args:
            name:      Guardrail name to append to *triggered* when *fn* returns ``True``.
            fn:        Zero-argument callable that runs the detector; must return ``bool``.
            triggered: Mutable list; this function appends *name* (or the error marker) in
                       place.

        Returns:
            ``True`` when the guardrail fired (including on exception), ``False`` otherwise.

        req: guardrails-019
        """
        try:
            result: bool = fn()
            if result:
                triggered.append(name)
            return result
        except Exception:  # pragma: no cover — detectors never raise; defensive only
            # Fail-safe: treat as triggered so the caller applies a block.
            triggered.append(_GUARDRAIL_ERROR_MARKER)
            return True

    # ---------------------------------------------------------------------- #
    # Public boundary — input (guardrails-003..007, guardrails-015..016, -019)
    # ---------------------------------------------------------------------- #

    async def run_input(
        self,
        message: str,
        active_lang: str,
    ) -> GuardrailResult:
        """Run all input guardrails on *message* and return the aggregate result.

        Policy (evaluated in priority order; block wins over redact wins over flag):

        +------------------+---------------+------------------------------------------+
        | detector         | triggered name| action                                   |
        +==================+===============+==========================================+
        | prompt_injection | prompt_injection | block (blocked=True, text="")          |
        | jailbreak        | jailbreak     | block                                    |
        | toxicity         | toxicity      | block                                    |
        | secret_leak      | secret_leak   | block                                    |
        | pii              | pii_detector  | redact (text=redact_pii(message))        |
        | off_topic        | off_topic     | flag  (text=message, blocked=False)      |
        +------------------+---------------+------------------------------------------+

        ``triggered`` accumulates **all** fired names even when a higher-priority action
        has already been determined.  For example, injection + PII yields
        ``action="block", triggered=["pii_detector", "prompt_injection"]``.

        When ``settings.guardrails_enabled`` is ``False`` all checks are skipped and a
        clean result with the original text is returned immediately (guardrails-016).

        Security-critical detectors (prompt_injection, jailbreak, toxicity) are wrapped
        via :meth:`_detect_safe` so any unexpected exception causes ``action="block"``
        rather than letting the turn proceed unchecked (guardrails-019).

        WHERE ``settings.guardrails_llm_enabled`` is ``True``, the deterministic result
        is AUGMENTED (union) with the optional LLM classifier verdict via
        :func:`~app.guardrails.llm.classify_input`.  The LLM layer never replaces or
        weakens a deterministic block — it can only add names and upgrade severity.
        Default off (``guardrails_llm_enabled=False``) means zero LLM call, no key
        needed, identical behaviour to the previous synchronous path (guardrails-015).

        Args:
            message:     The raw user message text.
            active_lang: ISO 639-1 code of the session's active language; forwarded to
                         the toxicity detector for per-language pattern selection.

        Returns:
            A :class:`GuardrailResult` describing the aggregate guardrail outcome.

        req: guardrails-003, guardrails-004, guardrails-005, guardrails-006,
             guardrails-007, guardrails-015, guardrails-016, guardrails-019
        """
        # guardrails-016: master kill-switch — skip all checks when disabled.
        if not self._settings.guardrails_enabled:
            return GuardrailResult(text=message)

        triggered: list[str] = []

        # ------------------------------------------------------------------ #
        # Security-critical detectors — wrapped for fail-safe (guardrails-019)
        # ------------------------------------------------------------------ #

        # req: guardrails-003
        is_injection: bool = self._detect_safe(
            "prompt_injection",
            lambda: self._detectors.detect_prompt_injection(message),
            triggered,
        )
        # req: guardrails-004
        is_jailbreak: bool = self._detect_safe(
            "jailbreak",
            lambda: self._detectors.detect_jailbreak(message),
            triggered,
        )
        # req: guardrails-005
        # A user may write toxic content in a language other than the locked session
        # language (e.g. a Spanish threat in an EN-locked session). Check across ALL
        # supported languages — same approach as run_output — to ensure detection is not
        # limited to active_lang.
        is_toxic: bool = self._detect_safe(
            "toxicity",
            lambda: any(
                self._detectors.detect_toxicity(message, lang) for lang in self._settings.supported
            ),
            triggered,
        )
        # req: guardrails-010 — secret-shaped content in the INPUT (a pasted API key,
        # gateway key, admin token, or system-prompt fragment) → block, mirroring the
        # output-side secret_leak guardrail.  Treating it as input-side too lets a user
        # who pastes a secret be stopped before the model sees it, and makes the
        # adversarial secret_leak cases trip.
        is_secret: bool = self._detect_safe(
            "secret_leak",
            lambda: self._detectors.detect_secret_leak(message),
            triggered,
        )

        # ------------------------------------------------------------------ #
        # Non-critical detectors — called directly (they never raise by contract)
        # ------------------------------------------------------------------ #

        # req: guardrails-006
        pii_matches: list[PiiMatch] = self._detectors.detect_pii(message)
        has_pii: bool = bool(pii_matches)
        if has_pii:
            triggered.append("pii_detector")

        # req: guardrails-007
        is_off_topic: bool = self._detectors.detect_off_topic(message)
        if is_off_topic:
            triggered.append("off_topic")

        # ------------------------------------------------------------------ #
        # Optional LLM augmentation — req: guardrails-015
        # AUGMENT (union) only — NEVER replace or weaken a deterministic block.
        # Default off (guardrails_llm_enabled=False) ⇒ classify_input returns set()
        # immediately with no gateway call, so this branch is effectively a no-op and
        # the function's behaviour is identical to its previous synchronous form.
        # ------------------------------------------------------------------ #

        if self._settings.guardrails_llm_enabled:
            llm_extra: set[str] = await classify_input(message, self._settings)
            existing: set[str] = set(triggered)
            for name in llm_extra - existing:
                triggered.append(name)
            # Re-derive blocking/flag booleans from the extended triggered set so the
            # per-category policy below reflects both deterministic AND LLM verdicts.
            # Union only: OR preserves deterministic True; LLM can upgrade False to True.
            triggered_names: set[str] = set(triggered)
            is_injection = is_injection or "prompt_injection" in triggered_names
            is_jailbreak = is_jailbreak or "jailbreak" in triggered_names
            is_toxic = is_toxic or "toxicity" in triggered_names
            is_off_topic = is_off_topic or "off_topic" in triggered_names

        # ------------------------------------------------------------------ #
        # Per-category policy: block > redact > flag > clean
        # ------------------------------------------------------------------ #

        if is_injection or is_jailbreak or is_toxic or is_secret:
            # Security-critical hit (or fail-safe error) → block the turn.
            # req: guardrails-003, guardrails-004, guardrails-005, guardrails-010, guardrails-019
            return GuardrailResult(
                triggered=triggered,
                action="block",
                text="",
                blocked=True,
            )

        if has_pii:
            # PII present but no security block → redact before forwarding.
            # req: guardrails-006
            return GuardrailResult(
                triggered=triggered,
                action="redact",
                text=self._detectors.redact_pii(message, pii_matches),
                blocked=False,
            )

        if is_off_topic:
            # Soft flag only — never block; caller carries the name.
            # req: guardrails-007
            return GuardrailResult(
                triggered=triggered,
                action="flag",
                text=message,
                blocked=False,
            )

        # Clean — no guardrail fired.
        return GuardrailResult(triggered=triggered, action="clean", text=message)

    # ---------------------------------------------------------------------- #
    # Public boundary — output (guardrails-008..010, guardrails-016)
    # ---------------------------------------------------------------------- #

    def run_output(
        self,
        reply: str,
    ) -> GuardrailResult:
        """Run all output guardrails on *reply* and return the aggregate result.

        Policy:

        +-------------+-------------+----------------------------------------------+
        | detector    | triggered   | action                                       |
        +=============+=============+==============================================+
        | toxicity    | toxicity    | block (blocked=True, text="")                |
        | secret_leak | secret_leak | block                                        |
        | pii         | pii_leak    | redact (text=redact_pii(reply))              |
        +-------------+-------------+----------------------------------------------+

        Block wins over redact when both are present.

        Toxicity is checked across all supported languages (EN/ES/PT) because
        ``active_lang`` is not available to this method — the reply should never be
        toxic regardless of language.

        When ``settings.guardrails_enabled`` is ``False``, returns a clean result
        immediately (guardrails-016).

        Args:
            reply: The candidate model reply text.

        Returns:
            A :class:`GuardrailResult` describing the aggregate guardrail outcome.

        req: guardrails-008, guardrails-009, guardrails-010, guardrails-016
        """
        # guardrails-016: master kill-switch.
        if not self._settings.guardrails_enabled:
            return GuardrailResult(text=reply)

        triggered: list[str] = []
        should_block: bool = False

        # req: guardrails-009 — toxicity in output → block.
        # All supported languages are checked since reply language is opaque here.
        # Uses settings.supported (the single source — app.config.SUPPORTED_LANGS).
        if any(self._detectors.detect_toxicity(reply, lang) for lang in self._settings.supported):
            triggered.append("toxicity")
            should_block = True

        # req: guardrails-010 — secret leak → block.
        if self._detectors.detect_secret_leak(reply):
            triggered.append("secret_leak")
            should_block = True

        # req: guardrails-008 — PII in output → redact (name: pii_leak, distinct from pii_detector).
        pii_matches: list[PiiMatch] = self._detectors.detect_pii(reply)
        has_pii_leak: bool = bool(pii_matches)
        if has_pii_leak:
            triggered.append("pii_leak")

        # Block wins over redact (guardrails-009/010 take priority over guardrails-008).
        if should_block:
            return GuardrailResult(
                triggered=triggered,
                action="block",
                text="",
                blocked=True,
            )

        if has_pii_leak:
            return GuardrailResult(
                triggered=triggered,
                action="redact",
                text=self._detectors.redact_pii(reply, pii_matches),
                blocked=False,
            )

        return GuardrailResult(triggered=triggered, action="clean", text=reply)
