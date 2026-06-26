"""Unit tests for compute_lang_confidence — LLM-vs-detector agreement score.

Covers all four rule branches:
  - Agreement → high score (≥0.6, ≤1.0)
  - Disagreement → low score (≤0.5, ≥0.0)
  - Detector unreliable (short input) → moderate score (== 0.55)
  - Detector failed (lang=None) → low score (≈0.3)

All values must be in [0, 1].

req: multilingual-005
Design contract: specs/multilingual/design.md §2.2
"""

from __future__ import annotations

import pytest

from app.lang.detector import DetectionResult
from app.lang.fusion import compute_lang_confidence

# ===========================================================================
# Agreement, disagreement, unreliable, and failed branches — all test compute_lang_confidence
# ===========================================================================


class TestComputeLangConfidence:
    # ---------------------------------------------------------------------------
    # Agreement (Rule 3): llm_lang == det.lang, det.is_reliable=True
    # ---------------------------------------------------------------------------

    def test_agreement_high_confidence_confidence(self) -> None:
        """llm_lang == det.lang and det.is_reliable → score in [0.6, 1.0].

        req: multilingual-005 — agreement → high score = min(1.0, 0.6 + 0.4 * det.confidence)
        """
        det = DetectionResult(lang="es", confidence=0.95, is_reliable=True)
        score = compute_lang_confidence("es", det)
        assert 0.6 <= score <= 1.0, f"Agreement score {score} not in [0.6, 1.0]"

    def test_agreement_formula_exact(self) -> None:
        """Agreement formula: score = min(1.0, 0.6 + 0.4 * det.confidence).

        req: multilingual-005 — formula pinned
        """
        det = DetectionResult(lang="pt", confidence=0.8, is_reliable=True)
        expected = min(1.0, 0.6 + 0.4 * 0.8)  # 0.92
        score = compute_lang_confidence("pt", det)
        assert score == pytest.approx(expected)

    def test_agreement_max_confidence_capped_at_1(self) -> None:
        """Perfect detector confidence must stay ≤ 1.0 (clamp guard).

        req: multilingual-005 — clamping
        """
        det = DetectionResult(lang="en", confidence=1.0, is_reliable=True)
        score = compute_lang_confidence("en", det)
        assert score <= 1.0

    # ---------------------------------------------------------------------------
    # Disagreement (Rule 4): llm_lang != det.lang, det.is_reliable=True
    # ---------------------------------------------------------------------------

    def test_disagreement_low_confidence(self) -> None:
        """LLM says 'en', detector says 'es' with high confidence → score ≤ 0.5.

        req: multilingual-005 — disagreement → low score = max(0.0, min(0.5, 1.0 - det.confidence))
        """
        det = DetectionResult(lang="es", confidence=0.9, is_reliable=True)
        score = compute_lang_confidence("en", det)
        assert 0.0 <= score <= 0.5, f"Disagreement score {score} not in [0.0, 0.5]"

    def test_disagreement_formula_exact(self) -> None:
        """Disagreement formula: score = max(0.0, min(0.5, 1.0 - det.confidence)).

        req: multilingual-005 — formula pinned
        """
        det = DetectionResult(lang="pt", confidence=0.7, is_reliable=True)
        expected = max(0.0, min(0.5, 1.0 - 0.7))  # 0.3
        score = compute_lang_confidence("en", det)
        assert score == pytest.approx(expected)

    def test_disagreement_very_high_det_confidence_rounds_to_zero(self) -> None:
        """Detector is very confident about a different language → score near 0.

        req: multilingual-005 — disagreement + high det.confidence → score ≈ 0
        """
        det = DetectionResult(lang="pt", confidence=1.0, is_reliable=True)
        score = compute_lang_confidence("es", det)
        assert score == pytest.approx(0.0)

    # ---------------------------------------------------------------------------
    # Detector unreliable / short input (Rule 2)
    # ---------------------------------------------------------------------------

    def test_detector_unreliable_returns_mid_score(self) -> None:
        """Detector ran but input was too short → moderate score == 0.55.

        req: multilingual-011, multilingual-005 — unreliable → weight LLM; score = 0.55
        """
        det = DetectionResult(lang="es", confidence=0.5, is_reliable=False)
        score = compute_lang_confidence("es", det)
        assert score == pytest.approx(0.55)

    def test_detector_unreliable_ignores_agreement(self) -> None:
        """Unreliable detection always returns 0.55 regardless of agreement.

        req: multilingual-011 — short-input rule fires before agree/disagree check
        """
        det_agree = DetectionResult(lang="es", confidence=0.9, is_reliable=False)
        det_disagree = DetectionResult(lang="pt", confidence=0.9, is_reliable=False)
        assert compute_lang_confidence("es", det_agree) == pytest.approx(0.55)
        assert compute_lang_confidence("es", det_disagree) == pytest.approx(0.55)

    # ---------------------------------------------------------------------------
    # Detector failed (Rule 1): det.lang is None or det.error is set
    # ---------------------------------------------------------------------------

    def test_detector_failed_lang_none_returns_low_score(self) -> None:
        """Detector failed (lang=None, no error set) → score == 0.3.

        req: multilingual-012, multilingual-005 — failure → low score ≈ 0.3
        """
        det = DetectionResult(lang=None, confidence=0.0, is_reliable=False)
        score = compute_lang_confidence("es", det)
        assert score == pytest.approx(0.3)

    def test_detector_failed_with_error_returns_low_score(self) -> None:
        """Detector failed with explicit error → score == 0.3.

        req: multilingual-012, multilingual-005 — error path → low score
        """
        det = DetectionResult(
            lang=None, confidence=0.0, is_reliable=False, error="RuntimeError: boom"
        )
        score = compute_lang_confidence("en", det)
        assert score == pytest.approx(0.3)

    def test_detector_failed_error_set_lang_also_present(self) -> None:
        """Even if lang is non-None, a populated error field triggers the failure rule (Rule 1).

        req: multilingual-012 — error field presence wins over lang presence
        """
        det = DetectionResult(lang="es", confidence=0.8, is_reliable=True, error="partial failure")
        score = compute_lang_confidence("es", det)
        # Rule 1 fires because det.error is not None — returns 0.3, not the agreement score
        assert score == pytest.approx(0.3)

    # ---------------------------------------------------------------------------
    # All values in [0, 1] — exhaustive clamp check
    # ---------------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("llm_lang", "lang", "confidence", "is_reliable", "error"),
        [
            ("es", "es", 1.0, True, None),  # agreement + max confidence
            ("en", "es", 1.0, True, None),  # disagreement + max confidence
            ("es", "es", 0.0, True, None),  # agreement + zero confidence
            ("en", "es", 0.0, True, None),  # disagreement + zero confidence
            ("es", "es", 0.5, False, None),  # unreliable
            (None, None, 0.0, False, None),  # failed, no llm_lang
            ("es", None, 0.0, False, "err"),  # failed with error
        ],
    )
    def test_all_cases_in_unit_interval(
        self,
        llm_lang: str | None,
        lang: str | None,
        confidence: float,
        is_reliable: bool,
        error: str | None,
    ) -> None:
        """Every case returns a float in [0, 1].

        req: multilingual-005 — all outputs clamped to [0, 1]
        """
        det = DetectionResult(
            lang=lang, confidence=confidence, is_reliable=is_reliable, error=error
        )
        score = compute_lang_confidence(llm_lang, det)
        assert 0.0 <= score <= 1.0, f"Score {score} outside [0, 1] for ({llm_lang!r}, {det!r})"
