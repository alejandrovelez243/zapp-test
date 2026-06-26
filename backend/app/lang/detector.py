"""Deterministic language detector — lingua wrapper over a bounded language set.

Satisfies:
  multilingual-002 — lingua-based detected_lang (ISO 639-1)
  multilingual-011 — is_reliable=False for input shorter than min_input_chars
  multilingual-012 — NEVER raises; error path returns DetectionResult(lang=None, ...)

Design contract: specs/multilingual/design.md §2.1
"""

from __future__ import annotations

from typing import Literal

from lingua import ConfidenceValue, Language, LanguageDetectorBuilder
from lingua import LanguageDetector as _LinguaDetector  # alias to avoid name clash
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# ISO 639-1 (2-char lowercase) -> lingua.Language mapping
# Bounded set: three supported languages + common Latin-script confusables so
# ES/EN/PT are not mis-classified as neighbouring languages.
# ---------------------------------------------------------------------------
_ISO_TO_LINGUA: dict[str, Language] = {
    "es": Language.SPANISH,
    "en": Language.ENGLISH,
    "pt": Language.PORTUGUESE,
    "fr": Language.FRENCH,
    "it": Language.ITALIAN,
    "de": Language.GERMAN,
}

# Confusables always included in the detector's language set, even when they
# are not in the supported list, to reduce false positives on ES/EN/PT text.
_CONFUSABLES: frozenset[str] = frozenset({"fr", "it", "de"})


class DetectionResult(BaseModel):
    """Output contract for a single language detection call.

    req: multilingual-002 — lang is ISO 639-1 lowercase (or None on failure)
    req: multilingual-011 — is_reliable reflects the short-input floor
    req: multilingual-012 — error field populated instead of raising
    """

    lang: str | None  # ISO 639-1 lowercase, e.g. "es", "en", "pt"; None on failure
    confidence: float = Field(ge=0.0, le=1.0)
    is_reliable: bool
    method: Literal["lingua"] = "lingua"
    error: str | None = None


class LanguageDetector:
    """Lingua-backed deterministic language detector.

    Constructor accepts its configuration by **dependency injection** — it does
    NOT call ``get_settings()`` at import time, keeping this module safe to import
    while other agents edit the config module in parallel.

    The internal lingua detector is built over a *bounded* language set
    (the supported languages + common confusables) for speed and low memory
    footprint relative to loading all 75 lingua languages.

    req: multilingual-002, multilingual-011, multilingual-012
    """

    def __init__(
        self,
        supported: tuple[str, ...] = ("es", "en", "pt"),
        min_input_chars: int = 12,
    ) -> None:
        self._min_input_chars: int = min_input_chars

        # Build the bounded lingua language set: supported + confusables.
        lang_set: set[Language] = set()
        for code in supported:
            mapped = _ISO_TO_LINGUA.get(code)
            if mapped is not None:
                lang_set.add(mapped)
        for code in _CONFUSABLES:
            if code not in supported:
                mapped = _ISO_TO_LINGUA.get(code)
                if mapped is not None:
                    lang_set.add(mapped)

        # lingua requires at least 2 languages in the set.
        if len(lang_set) < 2:
            lang_set.add(Language.ENGLISH)

        # Sort for deterministic build order (set ordering is non-deterministic).
        ordered: list[Language] = sorted(lang_set, key=lambda lang: lang.name)
        self._detector: _LinguaDetector = LanguageDetectorBuilder.from_languages(*ordered).build()

    def detect(self, text: str) -> DetectionResult:
        """Detect the language of ``text``.

        Returns a :class:`DetectionResult` with:

        * ``lang`` — ISO 639-1 lowercase code, or ``None`` when the detector
          yields zero signal (empty text, or all confidence values are 0).
        * ``confidence`` — top confidence score in ``[0, 1]``.
        * ``is_reliable`` — ``False`` when ``len(text.strip()) < min_input_chars``
          (req: multilingual-011), otherwise follows the detector signal.
        * ``error`` — populated (and ``lang`` set to ``None``) when any exception
          is caught; the method **never raises** (req: multilingual-012).

        All exceptions are caught internally so callers are never disrupted by
        detector failures; callers should check ``error is not None`` to detect
        degraded operation.
        """
        try:
            stripped: str = text.strip()
            reliable_length: bool = len(stripped) >= self._min_input_chars

            # compute_language_confidence_values returns the full language list
            # sorted by confidence descending; always non-empty for a built detector.
            # req: multilingual-002 — lingua API for top language + confidence
            confidence_values: list[ConfidenceValue] = (
                self._detector.compute_language_confidence_values(text)
            )

            if not confidence_values:
                # Unexpected empty list (edge case with exotic lingua builds)
                return DetectionResult(lang=None, confidence=0.0, is_reliable=False)

            top: ConfidenceValue = confidence_values[0]
            top_score: float = top.value

            if top_score == 0.0:
                # All confidence values are zero — no detectable signal (e.g. empty
                # text or purely numeric/punctuation input). Return no-lang result;
                # is_reliable governed by length floor still applies.
                return DetectionResult(
                    lang=None,
                    confidence=0.0,
                    # req: multilingual-011 — length floor always observed
                    is_reliable=False,
                )

            # Map lingua Language enum -> ISO 639-1 2-char lowercase code.
            # Language.iso_code_639_1 returns IsoCode639_1 whose .name is the
            # uppercase 2-char string (e.g. "ES"); .lower() normalises it.
            iso_code: str = top.language.iso_code_639_1.name.lower()

            return DetectionResult(
                lang=iso_code,
                confidence=top_score,
                # req: multilingual-011 — short input => is_reliable=False regardless
                # of what the detector thinks; still returns best-guess lang.
                is_reliable=reliable_length,
            )

        except Exception as exc:
            # req: multilingual-012 — catch ALL exceptions; never propagate.
            return DetectionResult(
                lang=None,
                confidence=0.0,
                is_reliable=False,
                error=str(exc),
            )
