"""Unit tests for LanguageDetector — deterministic lingua wrapper.

Covers:
  - Long supported sentence → reliable + correct ISO 639-1 lang code
  - Short input → is_reliable=False (length floor, not a failure)
  - Error path: monkeypatch the internal lingua call to raise → returns
    DetectionResult(lang=None, is_reliable=False, error=...) and NEVER raises

req: multilingual-002, multilingual-011, multilingual-012
Design contract: specs/multilingual/design.md §2.1
"""

from __future__ import annotations

from app.lang.detector import DetectionResult, LanguageDetector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A LanguageDetector instance shared across happy-path tests.
# (min_input_chars=12 is the production default.)
_DETECTOR = LanguageDetector(min_input_chars=12)


# ---------------------------------------------------------------------------
# Happy path and short-input floor
# ---------------------------------------------------------------------------


class TestLanguageDetector:
    def test_detect_long_spanish_sentence_reliable_es(self) -> None:
        """Long Spanish text → lang='es', is_reliable=True, no error.

        req: multilingual-002 — LanguageDetector.detect returns the correct ISO 639-1 code
        """
        result = _DETECTOR.detect(
            "Hola, me gustaría saber más sobre los cursos de filosofía "
            "que ofrecen en esta institución."
        )
        assert result.lang == "es", f"Expected 'es', got {result.lang!r}"
        assert result.is_reliable is True
        assert result.error is None
        assert 0.0 <= result.confidence <= 1.0

    def test_detect_long_english_sentence_reliable_en(self) -> None:
        """Long English text → lang='en', is_reliable=True, no error.

        req: multilingual-002 — lingua wrapper returns correct ISO 639-1 code
        """
        result = _DETECTOR.detect(
            "Hello, I would like to know more about the philosophy courses "
            "available at your school."
        )
        assert result.lang == "en", f"Expected 'en', got {result.lang!r}"
        assert result.is_reliable is True
        assert result.error is None
        assert 0.0 <= result.confidence <= 1.0

    def test_detect_long_portuguese_sentence_reliable_pt(self) -> None:
        """Long Portuguese text → lang='pt', is_reliable=True, no error.

        req: multilingual-002 — lingua wrapper returns correct ISO 639-1 code
        """
        result = _DETECTOR.detect(
            "Olá, gostaria de saber mais sobre os cursos de filosofia disponíveis na instituição."
        )
        assert result.lang == "pt", f"Expected 'pt', got {result.lang!r}"
        assert result.is_reliable is True
        assert result.error is None
        assert 0.0 <= result.confidence <= 1.0

    def test_detect_short_input_ok_is_unreliable(self) -> None:
        """'ok' is shorter than min_input_chars=12 → is_reliable=False, never raises.

        req: multilingual-011 — short input sets is_reliable=False (length floor)
        """
        result = _DETECTOR.detect("ok")
        assert result.is_reliable is False, "Short input must set is_reliable=False"
        # lang may be set or None depending on detector signal; what matters is unreliable
        assert 0.0 <= result.confidence <= 1.0
        assert result.error is None  # short input is NOT an error; it is just unreliable

    def test_detect_exactly_at_min_chars_boundary_reliable(self) -> None:
        """Input at exactly min_input_chars boundary is reliable when lang is detectable.

        req: multilingual-011 — the length floor is a strict less-than comparison
        """
        detector = LanguageDetector(min_input_chars=5)
        result = detector.detect("Hello")  # exactly 5 chars; len("Hello") >= 5 → reliable
        assert result.is_reliable is True

    def test_detect_below_min_chars_boundary_unreliable(self) -> None:
        """Input below the custom min_input_chars floor → is_reliable=False.

        req: multilingual-011 — custom floor is honoured
        """
        detector = LanguageDetector(min_input_chars=20)
        result = detector.detect("Hello, how are you?")  # 19 chars < 20
        assert result.is_reliable is False

    def test_detect_never_raises_on_internal_exception(self) -> None:
        """If the internal lingua detector raises, detect() returns a safe result, never raises.

        The lingua.LanguageDetector is a C-extension whose methods are read-only, so we
        swap the entire ``_detector`` instance attribute on our Python wrapper with a plain
        object whose ``compute_language_confidence_values`` always raises.

        req: multilingual-012 — NEVER raises; error path returns
        DetectionResult(lang=None, error=...)
        """

        class _RaisingDetector:
            """Stub that replaces the C-extension lingua detector to simulate an internal crash."""

            def compute_language_confidence_values(self, text: str) -> list[object]:
                raise RuntimeError("Simulated lingua failure")

        detector = LanguageDetector()
        # Replace the Python instance attribute (not the C-extension method).
        detector._detector = _RaisingDetector()  # type: ignore[assignment]

        # Must NOT raise even though the internal call does.
        result = detector.detect("This is a perfectly normal sentence that would be detected.")

        assert isinstance(result, DetectionResult)
        assert result.lang is None, "Error path must yield lang=None"
        assert result.is_reliable is False, "Error path must yield is_reliable=False"
        assert result.error is not None, "Error path must populate the error field"
        assert "Simulated lingua failure" in result.error
        assert result.confidence == 0.0

    def test_detect_result_model_valid_on_error_path(self) -> None:
        """The DetectionResult returned on error satisfies the Pydantic schema (ge/le constraints).

        req: multilingual-012 — error result must satisfy the DetectionResult schema
        """

        class _BoomDetector:
            def compute_language_confidence_values(self, text: str) -> list[object]:
                raise ValueError("bad state")

        detector = LanguageDetector()
        detector._detector = _BoomDetector()  # type: ignore[assignment]

        result = detector.detect("Any text here to trigger the mocked error.")
        # Pydantic re-validates via model_validate — must not raise ValidationError.
        validated = DetectionResult.model_validate(result.model_dump())
        assert validated.lang is None
        assert 0.0 <= validated.confidence <= 1.0
