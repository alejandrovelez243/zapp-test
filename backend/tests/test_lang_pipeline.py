"""Unit tests for LanguagePipeline — the detect+resolve facade.

Verifies that:
  - LanguagePipeline.detect delegates correctly to LanguageDetector
  - LanguagePipeline.resolve delegates correctly to resolve_active_lang
  - The pipeline composes detect+resolve coherently end-to-end
  - Settings are forwarded correctly (supported set, min_input_chars)
  - Pure functions (fusion, state) are NOT replaced — the pipeline just calls them

These tests intentionally do NOT duplicate the exhaustive branch coverage already
in test_detector.py / test_state.py / test_fusion.py; they cover the delegation
contract and composition.

req: multilingual-002, multilingual-003, multilingual-004, multilingual-011, multilingual-012
Design contract: specs/multilingual/design.md §2.1 / §2.3
"""

from __future__ import annotations

from app.agents.session import ConversationSession
from app.config import Settings
from app.lang.detector import DetectionResult
from app.lang.pipeline import LanguagePipeline
from app.lang.state import ActiveLangDecision

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**overrides: object) -> Settings:
    """Return a Settings instance with test-safe required fields + optional overrides."""
    return Settings(
        database_url="sqlite:///:memory:",
        admin_token="test-admin",
        **overrides,  # type: ignore[arg-type]
    )


def _fresh_session(session_id: str = "pipe-s1") -> ConversationSession:
    """Return a ConversationSession with no prior active_lang (first-turn state)."""
    return ConversationSession(id=session_id)


def _locked_session(active_lang: str, session_id: str = "pipe-s1") -> ConversationSession:
    """Return a ConversationSession already locked to *active_lang*."""
    s = ConversationSession(id=session_id)
    s.active_lang = active_lang
    return s


# ===========================================================================
# Construction
# ===========================================================================


class TestLanguagePipelineConstruction:
    def test_pipeline_constructs_with_settings(self) -> None:
        """LanguagePipeline.__init__ accepts a Settings instance without raising.

        req: multilingual-002 — pipeline builds the detector successfully
        """
        pipeline = LanguagePipeline(_cfg())
        assert pipeline is not None

    def test_pipeline_respects_custom_min_input_chars(self) -> None:
        """min_input_chars is forwarded to the detector — short inputs become unreliable.

        req: multilingual-011 — length floor configured via settings
        """
        cfg = _cfg(min_input_chars=100)
        pipeline = LanguagePipeline(cfg)
        result = pipeline.detect("Hello, how are you today?")  # < 100 chars
        assert result.is_reliable is False


# ===========================================================================
# detect() delegation
# ===========================================================================


class TestLanguagePipelineDetect:
    def test_detect_returns_detection_result(self) -> None:
        """pipeline.detect returns a DetectionResult (correct return type).

        req: multilingual-002 — detect returns DetectionResult with lang, confidence, etc.
        """
        pipeline = LanguagePipeline(_cfg())
        result = pipeline.detect(
            "Hello, I would like to learn more about the philosophy courses at your school."
        )
        assert isinstance(result, DetectionResult)
        assert 0.0 <= result.confidence <= 1.0

    def test_detect_long_spanish_reliable(self) -> None:
        """Long Spanish text via pipeline → lang='es', is_reliable=True.

        req: multilingual-002 — pipeline detect correctly identifies Spanish
        """
        pipeline = LanguagePipeline(_cfg())
        result = pipeline.detect(
            "Hola, me gustaría saber más sobre los cursos de filosofía disponibles."
        )
        assert result.lang == "es"
        assert result.is_reliable is True
        assert result.error is None

    def test_detect_long_english_reliable(self) -> None:
        """Long English text via pipeline → lang='en', is_reliable=True.

        req: multilingual-002 — pipeline detect correctly identifies English
        """
        pipeline = LanguagePipeline(_cfg())
        result = pipeline.detect(
            "Hello, I would like to know more about the philosophy courses at your school."
        )
        assert result.lang == "en"
        assert result.is_reliable is True

    def test_detect_long_portuguese_reliable(self) -> None:
        """Long Portuguese text via pipeline → lang='pt', is_reliable=True.

        req: multilingual-002 — pipeline detect correctly identifies Portuguese
        """
        pipeline = LanguagePipeline(_cfg())
        result = pipeline.detect(
            "Olá, gostaria de saber mais sobre os cursos de filosofia disponíveis."
        )
        assert result.lang == "pt"
        assert result.is_reliable is True

    def test_detect_short_input_unreliable(self) -> None:
        """Short input via pipeline → is_reliable=False (length floor delegated).

        req: multilingual-011 — pipeline correctly delegates the short-input floor
        """
        pipeline = LanguagePipeline(_cfg(min_input_chars=12))
        result = pipeline.detect("ok")
        assert result.is_reliable is False
        assert result.error is None  # short input is NOT an error

    def test_detect_never_raises_on_internal_error(self) -> None:
        """If the underlying detector errors, pipeline.detect never raises.

        req: multilingual-012 — pipeline inherits the never-raises guarantee
        """

        class _BoomDetector:
            def compute_language_confidence_values(self, text: str) -> list[object]:
                raise RuntimeError("simulated boom")

        pipeline = LanguagePipeline(_cfg())
        pipeline._detector._detector = _BoomDetector()  # type: ignore[assignment]

        result = pipeline.detect("This is a sentence that would normally be detected.")
        assert isinstance(result, DetectionResult)
        assert result.lang is None
        assert result.error is not None
        assert result.is_reliable is False


# ===========================================================================
# resolve() delegation
# ===========================================================================


class TestLanguagePipelineResolve:
    def test_resolve_returns_active_lang_decision(self) -> None:
        """pipeline.resolve returns an ActiveLangDecision (correct return type).

        req: multilingual-003 — resolve returns ActiveLangDecision with active_lang
        """
        pipeline = LanguagePipeline(_cfg())
        det = DetectionResult(lang="es", confidence=0.9, is_reliable=True)
        decision = pipeline.resolve(_fresh_session(), det)
        assert isinstance(decision, ActiveLangDecision)

    def test_resolve_first_turn_locks_to_detected_lang(self) -> None:
        """First-turn, reliable detection → active_lang locked to detected language.

        req: multilingual-004 — first-turn lock delegated correctly through pipeline
        """
        pipeline = LanguagePipeline(_cfg())
        det = DetectionResult(lang="pt", confidence=0.95, is_reliable=True)
        decision = pipeline.resolve(_fresh_session(), det)

        assert decision.active_lang == "pt"
        assert decision.first_turn is True
        assert decision.locked is True
        assert decision.fallback_used is False
        assert decision.needs_review is False

    def test_resolve_first_turn_unsupported_lang_uses_fallback(self) -> None:
        """First-turn with an unsupported language → fallback_lang + needs_review.

        req: multilingual-009 — unsupported first-turn → fallback
        """
        pipeline = LanguagePipeline(_cfg(fallback_lang="en"))
        det = DetectionResult(lang="de", confidence=0.9, is_reliable=True)
        decision = pipeline.resolve(_fresh_session(), det)

        assert decision.active_lang == "en"
        assert decision.fallback_used is True
        assert decision.needs_review is True

    def test_resolve_locked_session_kept_when_autoswitch_off(self) -> None:
        """Locked session + autoswitch=False → active_lang unchanged, no switch.

        req: multilingual-014 — pipeline forwards settings.lang_autoswitch correctly
        """
        pipeline = LanguagePipeline(_cfg(lang_autoswitch=False))
        det = DetectionResult(lang="pt", confidence=0.9, is_reliable=True)
        decision = pipeline.resolve(_locked_session("es"), det)

        assert decision.active_lang == "es"
        assert decision.switched is False

    def test_resolve_forwards_settings_supported_set(self) -> None:
        """The pipeline's supported set is forwarded to the state machine.

        When detected lang is not in supported, the locked lang is kept + needs_review.
        req: multilingual-008 — unsupported on locked session
        """
        # Only 'en' and 'es' supported; 'pt' is unsupported in this custom config.
        pipeline = LanguagePipeline(_cfg(supported=("en", "es"), fallback_lang="en"))
        det = DetectionResult(lang="pt", confidence=0.9, is_reliable=True)
        decision = pipeline.resolve(_locked_session("en"), det)

        assert decision.active_lang == "en"
        assert decision.needs_review is True


# ===========================================================================
# End-to-end composition: detect → resolve
# ===========================================================================


class TestLanguagePipelineEndToEnd:
    def test_detect_then_resolve_spanish_first_turn(self) -> None:
        """Full pipeline: detect Spanish → resolve on first turn → lock to 'es'.

        req: multilingual-002, multilingual-004
        """
        pipeline = LanguagePipeline(_cfg())
        message = "Me gustaría inscribirme en el curso de filosofía antigua por favor."
        det = pipeline.detect(message)
        decision = pipeline.resolve(_fresh_session(), det)

        assert det.lang == "es"
        assert decision.active_lang == "es"
        assert decision.first_turn is True
        assert decision.locked is True

    def test_detect_then_resolve_english_first_turn(self) -> None:
        """Full pipeline: detect English → resolve on first turn → lock to 'en'.

        req: multilingual-002, multilingual-004
        """
        pipeline = LanguagePipeline(_cfg())
        message = "I would like to enroll in the ancient philosophy course please."
        det = pipeline.detect(message)
        decision = pipeline.resolve(_fresh_session(), det)

        assert det.lang == "en"
        assert decision.active_lang == "en"
        assert decision.first_turn is True

    def test_detect_then_resolve_locked_session_preserved(self) -> None:
        """Full pipeline: locked 'es' session + autoswitch off → decision preserves 'es'.

        req: multilingual-003, multilingual-014
        """
        pipeline = LanguagePipeline(_cfg(lang_autoswitch=False))
        # Message is in English but session is locked to Spanish.
        message = "Hello, what courses do you have available today?"
        det = pipeline.detect(message)
        decision = pipeline.resolve(_locked_session("es"), det)

        assert decision.active_lang == "es"
        assert decision.first_turn is False
        assert decision.switched is False
