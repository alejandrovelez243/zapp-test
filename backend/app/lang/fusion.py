"""Language confidence fusion — agreement score between the LLM and the lingua detector.

Implements ``compute_lang_confidence`` which fuses:
- the LLM's self-reported ``detected_lang``
- a ``DetectionResult`` from the deterministic lingua detector

into a single ``lang_confidence`` float in ``[0, 1]``.

req: multilingual-005
Design contract: specs/multilingual/design.md §2.2
"""

from __future__ import annotations

from app.lang.detector import DetectionResult


def _clamp(value: float) -> float:
    """Clamp *value* to the closed interval ``[0.0, 1.0]``."""
    return max(0.0, min(1.0, value))


def compute_lang_confidence(llm_lang: str | None, det: DetectionResult) -> float:
    """Return the agreement score between *llm_lang* and *det* as a float in ``[0, 1]``.

    Priority rules (evaluated top-to-bottom, first match wins):

    1. **Detector failed** — ``det.lang is None`` or ``det.error`` is set:
       the detector yielded no usable signal; return a low score (``0.3``) and
       fall back to the LLM's self-report downstream.
       req: multilingual-012

    2. **Detector unreliable** — ``det.is_reliable`` is ``False`` (input shorter
       than ``min_input_chars``): the detection is too uncertain to override the
       LLM; return a moderate score (``0.55``, equal to ``lang_confidence_min``)
       that weights the LLM signal.
       req: multilingual-011

    3. **Agreement** — both signals present and equal (``llm_lang == det.lang``):
       return a high score: ``min(1.0, 0.6 + 0.4 * det.confidence)``.
       req: multilingual-005

    4. **Disagreement** — both signals present but differ (``llm_lang != det.lang``):
       return a low score: ``max(0.0, min(0.5, 1.0 - det.confidence))``.
       req: multilingual-005, multilingual-010

    All returned values are clamped to ``[0.0, 1.0]``.

    This is a **pure function** — no I/O, no globals, no side-effects.

    Args:
        llm_lang: ISO 639-1 language code self-reported by the LLM, or ``None``
                  when the LLM did not emit a code.
        det:      :class:`~app.lang.detector.DetectionResult` from the lingua
                  detector for the same input text.

    Returns:
        A float in ``[0.0, 1.0]`` representing the agreement confidence.
    """
    # Rule 1 — detector failed; no usable detector signal.
    # req: multilingual-012
    if det.lang is None or det.error is not None:
        return _clamp(0.3)

    # Rule 2 — detector ran but input was too short to be reliable.
    # Weight the LLM signal; return a moderate score at the threshold boundary.
    # req: multilingual-011
    if not det.is_reliable:
        return _clamp(0.55)

    # At this point det.lang is a non-None str and the result is reliable.
    # Rule 3 — both signals agree.
    # req: multilingual-005
    if llm_lang == det.lang:
        return _clamp(0.6 + 0.4 * det.confidence)

    # Rule 4 — signals disagree; confidence inversely proportional to detector certainty.
    # req: multilingual-005, multilingual-010
    return _clamp(max(0.0, min(0.5, 1.0 - det.confidence)))
