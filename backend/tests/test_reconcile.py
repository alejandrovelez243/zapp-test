"""Unit tests for the reconcile() pure function (app/fusion/reconcile.py).

reconcile() is side-effect-free — no I/O, no mocking needed.
Each test constructs a GeoContext + inputs and asserts the ReconcileResult fields.

Requirement traceability:
  orchestrator-and-fusion-007  agreement (lang ≈ geo, ok, no divergence) → high score
  orchestrator-and-fusion-008  confidence_score computed deterministically; clamped [0,1]
  orchestrator-and-fusion-009  geo.source="error" → score *= 0.85; needs_review=False
  orchestrator-and-fusion-010  source="private_ip"/"disabled" → no penalty, no needs_review
  orchestrator-and-fusion-011  geo locale primary lang ≠ active_lang → score *= 0.7;
                               needs_review=False; divergence=True
  orchestrator-and-fusion-012  source="ipapi", ok=False → no penalty, no needs_review
  orchestrator-and-fusion-014  lang_fallback_used=True → needs_review=True
"""

from __future__ import annotations

import pytest

from app.fusion.geo import GeoContext
from app.fusion.reconcile import ReconcileResult, reconcile

# ---------------------------------------------------------------------------
# Helpers — canonical GeoContexts for each source branch
# ---------------------------------------------------------------------------

_GEO_OK_ES = GeoContext(
    country="ES",
    timezone="Europe/Madrid",
    locale="es-ES",
    source="ipapi",
    ok=True,
)

_GEO_OK_MX = GeoContext(
    country="MX",
    timezone="America/Mexico_City",
    locale="es-MX",
    source="ipapi",
    ok=True,
)

_GEO_OK_BR = GeoContext(
    country="BR",
    timezone="America/Sao_Paulo",
    locale="pt-BR",
    source="ipapi",
    ok=True,
)

_GEO_ERROR = GeoContext(source="error", ok=False)
_GEO_PRIVATE = GeoContext(source="private_ip", ok=False)
_GEO_DISABLED = GeoContext(source="disabled", ok=False)

# ipapi succeeded but REST Countries enrichment failed — country is known, locale is default.
_GEO_IPAPI_RC_FAIL = GeoContext(
    country="MX",
    timezone="UTC",
    locale="en-US",
    source="ipapi",
    ok=False,  # req-012: RC failed → ok=False on an "ipapi" source
)

_GEO_CACHE_ES = GeoContext(
    country="ES",
    timezone="Europe/Madrid",
    locale="es-ES",
    source="cache",
    ok=True,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReconcile:
    """Every branch of the deterministic reconcile() function.

    Pure function — no mocking required.
    """

    # ------------------------------------------------------------------
    # req-007: agreement → high score, no review
    # ------------------------------------------------------------------

    def test_agreement_no_divergence_high_score_no_review(self) -> None:
        """Geo ok, locale language matches active_lang → score unchanged, no review.

        geo.locale="es-ES" → primary_lang="es" == active_lang="es" → no divergence.
        lang_confidence=0.9 → confidence_score=0.9.

        req: orchestrator-and-fusion-007
        """
        result = reconcile(
            _GEO_OK_ES,
            lang_confidence=0.9,
            active_lang="es",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.9)
        assert result.needs_review is False
        assert result.divergence is False

    def test_agreement_with_mx_locale_and_es_active_lang(self) -> None:
        """es-MX locale → primary_lang="es" == active_lang="es" → agreement.

        req: orchestrator-and-fusion-007
        """
        result = reconcile(
            _GEO_OK_MX,
            lang_confidence=0.85,
            active_lang="es",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.85)
        assert result.needs_review is False
        assert result.divergence is False

    def test_agreement_pt_locale_matches_pt_active_lang(self) -> None:
        """pt-BR locale → primary_lang="pt" == active_lang="pt" → no divergence.

        req: orchestrator-and-fusion-007
        """
        result = reconcile(
            _GEO_OK_BR,
            lang_confidence=0.88,
            active_lang="pt",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.88)
        assert result.needs_review is False
        assert result.divergence is False

    # ------------------------------------------------------------------
    # req-011: divergence → score *= 0.7, needs_review=False, divergence=True
    # Geo divergence DAMPS confidence but does NOT set needs_review — expats /
    # travellers writing in their own language abroad are a normal case.
    # ------------------------------------------------------------------

    def test_divergence_geo_locale_ne_active_lang_damps_score(self) -> None:
        """pt-BR locale → primary_lang="pt" ≠ active_lang="es" → divergence.

        score = 0.9 * 0.7 = 0.63.  needs_review stays False (geo-only signal).

        req: orchestrator-and-fusion-011
        """
        result = reconcile(
            _GEO_OK_BR,
            lang_confidence=0.9,
            active_lang="es",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.9 * 0.7)
        assert result.needs_review is False
        assert result.divergence is True

    def test_divergence_es_locale_ne_pt_active_lang(self) -> None:
        """es-MX locale → primary_lang="es" ≠ active_lang="pt" → divergence.

        score = 0.8 * 0.7.  needs_review stays False.

        req: orchestrator-and-fusion-011
        """
        result = reconcile(
            _GEO_OK_MX,
            lang_confidence=0.8,
            active_lang="pt",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.8 * 0.7)
        assert result.needs_review is False
        assert result.divergence is True

    # ------------------------------------------------------------------
    # req-009: geo error → score *= 0.85, needs_review=False
    # Geo-IP failure DAMPS confidence but does NOT set needs_review — a flaky
    # geo-IP API is not a content-quality signal.
    # ------------------------------------------------------------------

    def test_geo_error_damps_score_and_sets_review(self) -> None:
        """source="error" → score *= 0.85, needs_review=False, divergence=False.

        req: orchestrator-and-fusion-009
        """
        result = reconcile(
            _GEO_ERROR,
            lang_confidence=0.8,
            active_lang="es",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.8 * 0.85)
        assert result.needs_review is False
        assert result.divergence is False

    def test_geo_error_low_lang_confidence_still_clamped(self) -> None:
        """Even with a very low starting lang_confidence, geo-error damping stays ≥ 0.

        req: orchestrator-and-fusion-009, orchestrator-and-fusion-008
        """
        result = reconcile(
            _GEO_ERROR,
            lang_confidence=0.3,
            active_lang="en",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.3 * 0.85)
        assert 0.0 <= result.confidence_score <= 1.0
        assert result.needs_review is False

    # ------------------------------------------------------------------
    # req-010: private_ip / disabled → no penalty, no needs_review
    # ------------------------------------------------------------------

    def test_private_ip_no_penalty_no_review(self) -> None:
        """source="private_ip" → no score penalty, no needs_review.

        req: orchestrator-and-fusion-010
        """
        result = reconcile(
            _GEO_PRIVATE,
            lang_confidence=0.85,
            active_lang="en",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.85)
        assert result.needs_review is False
        assert result.divergence is False

    def test_disabled_no_penalty_no_review(self) -> None:
        """source="disabled" (geo_fusion_enabled=False) → no penalty, no needs_review.

        req: orchestrator-and-fusion-010, orchestrator-and-fusion-015
        """
        result = reconcile(
            _GEO_DISABLED,
            lang_confidence=0.75,
            active_lang="pt",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.75)
        assert result.needs_review is False
        assert result.divergence is False

    def test_cache_source_no_geo_penalty_when_consistent(self) -> None:
        """source="cache" with matching locale → treated like a normal ok geo.

        The cache is a transparent alias for a prior successful resolve; when the
        cached locale is consistent with active_lang there is no extra penalty.

        req: orchestrator-and-fusion-017 (cache is a normal, penaltyless source)
        """
        result = reconcile(
            _GEO_CACHE_ES,
            lang_confidence=0.9,
            active_lang="es",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.9)
        assert result.needs_review is False
        assert result.divergence is False

    # ------------------------------------------------------------------
    # req-012: REST Countries fail (source="ipapi", ok=False) → no penalty, no needs_review
    # REST Countries enrichment is best-effort; its failure does not affect turn quality.
    # ------------------------------------------------------------------

    def test_rest_fail_no_penalty_no_review(self) -> None:
        """source="ipapi", ok=False → confidence_score unchanged, needs_review=False.

        req: orchestrator-and-fusion-012
        """
        result = reconcile(
            _GEO_IPAPI_RC_FAIL,
            lang_confidence=0.8,
            active_lang="en",
            lang_fallback_used=False,
        )

        # Rule 4: ipapi+not ok → no review, no score multiplication.
        assert result.confidence_score == pytest.approx(0.8)
        assert result.needs_review is False
        assert result.divergence is False

    # ------------------------------------------------------------------
    # req-014: lang_fallback_used → needs_review=True
    # ------------------------------------------------------------------

    def test_lang_fallback_used_sets_review(self) -> None:
        """Unsupported language fell back to configured fallback → needs_review=True.

        req: orchestrator-and-fusion-014
        """
        result = reconcile(
            _GEO_DISABLED,
            lang_confidence=0.7,
            active_lang="en",
            lang_fallback_used=True,
        )

        assert result.needs_review is True
        assert result.confidence_score == pytest.approx(0.7)
        assert result.divergence is False

    def test_lang_fallback_used_compounds_with_geo_error(self) -> None:
        """geo error damps score (*0.85); lang_fallback sets needs_review.

        needs_review=True comes from lang_fallback_used only; geo-error alone
        would NOT set needs_review under the new semantics.

        req: orchestrator-and-fusion-009, orchestrator-and-fusion-014
        """
        result = reconcile(
            _GEO_ERROR,
            lang_confidence=0.6,
            active_lang="en",
            lang_fallback_used=True,
        )

        assert result.confidence_score == pytest.approx(0.6 * 0.85)
        assert result.needs_review is True

    # ------------------------------------------------------------------
    # req-008: score clamped to [0.0, 1.0]
    # ------------------------------------------------------------------

    def test_score_clamped_to_one_when_starting_above_one(self) -> None:
        """lang_confidence > 1.0 with no damping → confidence_score clamped to 1.0.

        req: orchestrator-and-fusion-008
        """
        result = reconcile(
            _GEO_PRIVATE,  # no penalty source
            lang_confidence=1.5,
            active_lang="en",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(1.0)

    def test_score_clamped_to_zero_when_starting_below_zero(self) -> None:
        """lang_confidence < 0.0 → confidence_score clamped to 0.0.

        req: orchestrator-and-fusion-008
        """
        result = reconcile(
            _GEO_PRIVATE,  # no penalty source
            lang_confidence=-0.3,
            active_lang="es",
            lang_fallback_used=False,
        )

        assert result.confidence_score == pytest.approx(0.0)

    @pytest.mark.parametrize(
        ("lang_confidence", "geo", "active_lang", "fallback"),
        [
            (0.9, _GEO_OK_ES, "es", False),  # agreement
            (0.9, _GEO_OK_BR, "es", False),  # divergence → *0.7
            (0.8, _GEO_ERROR, "es", False),  # geo error → *0.85
            (0.85, _GEO_PRIVATE, "en", False),  # private_ip
            (0.85, _GEO_DISABLED, "en", True),  # disabled + fallback
            (0.8, _GEO_IPAPI_RC_FAIL, "en", False),  # RC fail
            (1.5, _GEO_PRIVATE, "en", False),  # above 1
            (-0.1, _GEO_ERROR, "es", False),  # below 0
        ],
    )
    def test_confidence_score_always_in_unit_interval(
        self,
        lang_confidence: float,
        geo: GeoContext,
        active_lang: str,
        fallback: bool,
    ) -> None:
        """All combinations produce a confidence_score in [0.0, 1.0].

        req: orchestrator-and-fusion-008 — clamp is unconditional
        """
        result = reconcile(
            geo,
            lang_confidence=lang_confidence,
            active_lang=active_lang,
            lang_fallback_used=fallback,
        )
        assert isinstance(result, ReconcileResult)
        assert 0.0 <= result.confidence_score <= 1.0, (
            f"score={result.confidence_score} out of [0,1] for "
            f"lang_confidence={lang_confidence}, geo.source={geo.source!r}"
        )
