"""Language pipeline — encapsulates detect → resolve in a single stateful object.

Holds the lingua ``LanguageDetector`` instance (state = detector + settings) and
exposes the two-step flow as typed methods so callers never construct the detector
or call the pure state-machine helpers directly.

``fusion.compute_lang_confidence`` and ``state.resolve_active_lang`` are kept as
PURE functions; this class only delegates to them — it does NOT replace them.

Requirements satisfied:
  multilingual-002 — lingua-based detected_lang via LanguageDetector.detect
  multilingual-003 — active_lang constrained to supported set via resolve_active_lang
  multilingual-004 — first-turn lock via resolve_active_lang
  multilingual-011 — short-input floor delegated to LanguageDetector
  multilingual-012 — error path delegated to LanguageDetector (never raises)

Design contract: specs/multilingual/design.md §2.1 / §2.3
"""

from __future__ import annotations

from app.agents.session import ConversationSession
from app.config import Settings
from app.lang.detector import DetectionResult, LanguageDetector
from app.lang.state import ActiveLangDecision, resolve_active_lang


class LanguagePipeline:
    """Stateful language pipeline: builds and holds a ``LanguageDetector`` instance.

    Parameters
    ----------
    settings:
        Application settings.  ``settings.supported`` and ``settings.min_input_chars``
        configure the underlying lingua detector; ``settings`` is forwarded verbatim
        to ``resolve_active_lang`` on every ``resolve()`` call.

    Usage
    -----
    .. code-block:: python

        pipeline = LanguagePipeline(settings)
        det = pipeline.detect(message)          # -> DetectionResult
        decision = pipeline.resolve(session, det)  # -> ActiveLangDecision
    """

    def __init__(self, settings: Settings) -> None:
        self._settings: Settings = settings
        # req: multilingual-002, multilingual-011, multilingual-012
        # Build once; the detector is heavyweight (lingua C-extension); reuse across calls.
        self._detector: LanguageDetector = LanguageDetector(
            supported=settings.supported,
            min_input_chars=settings.min_input_chars,
        )

    def detect(self, message: str) -> DetectionResult:
        """Detect the language of *message* via the held ``LanguageDetector``.

        Delegates entirely to ``LanguageDetector.detect``; never raises.

        req: multilingual-002, multilingual-011, multilingual-012
        """
        return self._detector.detect(message)

    def resolve(
        self,
        session: ConversationSession,
        detection: DetectionResult,
    ) -> ActiveLangDecision:
        """Resolve the active language for this turn via the pure state machine.

        Delegates to ``resolve_active_lang(session, detection, self._settings)``.

        req: multilingual-003, multilingual-004, multilingual-008, multilingual-009,
             multilingual-011, multilingual-014
        """
        return resolve_active_lang(session, detection, self._settings)
