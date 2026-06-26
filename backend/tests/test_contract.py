"""Tests for the canonical TurnOutput + GuardrailReport Pydantic models.

Requirement: platform-scaffold-011
  THE SYSTEM SHALL define the canonical TurnOutput and GuardrailReport Pydantic models
  exactly per the constitution's per-turn JSON contract.

Checks:
  - All nine fields present with correct names.
  - lang_confidence / confidence_score reject values outside [0.0, 1.0].
  - detected_lang / active_lang enforce exactly-2-character length.
  - detected_country accepts None.
"""

import pytest
from pydantic import ValidationError

from app.contract import GuardrailReport, TurnOutput

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VALID_KWARGS: dict[str, object] = {
    "reply": "Here is your answer.",
    "detected_lang": "en",
    "active_lang": "en",
    "lang_confidence": 0.95,
    "final_normalized_text": "Here is your answer.",
    "detected_country": None,
    "confidence_score": 0.88,
    "needs_review": False,
    "guardrails": GuardrailReport(),
}


def _make(**overrides: object) -> TurnOutput:
    """Build a TurnOutput from the valid template, applying field overrides."""
    return TurnOutput(**{**_VALID_KWARGS, **overrides})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Shape: exactly 9 fields  # platform-scaffold-011
# ---------------------------------------------------------------------------


def test_turn_output_has_exactly_nine_fields() -> None:
    """TurnOutput.model_dump() must contain exactly the nine contract fields."""
    output = _make()
    data = output.model_dump()
    expected = {
        "reply",
        "detected_lang",
        "active_lang",
        "lang_confidence",
        "final_normalized_text",
        "detected_country",
        "confidence_score",
        "needs_review",
        "guardrails",
    }
    assert set(data.keys()) == expected
    assert len(data) == 9  # no extra fields sneaked in


def test_guardrail_report_defaults_to_empty_lists() -> None:
    """GuardrailReport() must default both lists to empty."""
    report = GuardrailReport()
    assert report.input == []
    assert report.output == []


def test_guardrail_report_stores_triggered_names() -> None:
    """GuardrailReport carries the names of triggered guardrails."""
    report = GuardrailReport(input=["pii_detector"], output=["toxicity"])
    assert report.input == ["pii_detector"]
    assert report.output == ["toxicity"]


# ---------------------------------------------------------------------------
# lang_confidence constraints: ge=0.0, le=1.0  # platform-scaffold-011
# ---------------------------------------------------------------------------


def test_lang_confidence_accepts_zero() -> None:
    assert _make(lang_confidence=0.0).lang_confidence == 0.0


def test_lang_confidence_accepts_one() -> None:
    assert _make(lang_confidence=1.0).lang_confidence == 1.0


def test_lang_confidence_rejects_below_zero() -> None:
    with pytest.raises(ValidationError):
        _make(lang_confidence=-0.01)


def test_lang_confidence_rejects_above_one() -> None:
    with pytest.raises(ValidationError):
        _make(lang_confidence=1.01)


# ---------------------------------------------------------------------------
# confidence_score constraints: ge=0.0, le=1.0  # platform-scaffold-011
# ---------------------------------------------------------------------------


def test_confidence_score_accepts_zero() -> None:
    assert _make(confidence_score=0.0).confidence_score == 0.0


def test_confidence_score_accepts_one() -> None:
    assert _make(confidence_score=1.0).confidence_score == 1.0


def test_confidence_score_rejects_below_zero() -> None:
    with pytest.raises(ValidationError):
        _make(confidence_score=-0.01)


def test_confidence_score_rejects_above_one() -> None:
    with pytest.raises(ValidationError):
        _make(confidence_score=1.01)


# ---------------------------------------------------------------------------
# detected_lang / active_lang: exactly 2 chars  # platform-scaffold-011
# ---------------------------------------------------------------------------


def test_detected_lang_rejects_single_char() -> None:
    with pytest.raises(ValidationError):
        _make(detected_lang="e")


def test_detected_lang_rejects_three_chars() -> None:
    with pytest.raises(ValidationError):
        _make(detected_lang="eng")


def test_active_lang_rejects_single_char() -> None:
    with pytest.raises(ValidationError):
        _make(active_lang="e")


def test_active_lang_rejects_three_chars() -> None:
    with pytest.raises(ValidationError):
        _make(active_lang="eng")


# ---------------------------------------------------------------------------
# detected_country: accepts None  # platform-scaffold-011
# ---------------------------------------------------------------------------


def test_detected_country_accepts_none() -> None:
    output = _make(detected_country=None)
    assert output.detected_country is None


def test_detected_country_accepts_valid_alpha2() -> None:
    """CountryAlpha2 coerces a valid 2-char code string."""
    output = _make(detected_country="US")
    assert str(output.detected_country) == "US"
