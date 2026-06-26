"""Deterministic reconciliation of geo + language signals → confidence_score.

Pure function; no I/O, no side-effects.  Called from the orchestrator's
``output_validator`` after the multilingual layer has set ``lang_confidence``
and ``active_lang``.

Requirement traceability:
  orchestrator-and-fusion-007  high agreement (lang ≈ geo ok, no divergence) → high score
  orchestrator-and-fusion-008  confidence_score computed deterministically (pure fn)
  orchestrator-and-fusion-009  geo error → score *= 0.85; no needs_review
  orchestrator-and-fusion-010  private_ip / disabled → no penalty, no needs_review
  orchestrator-and-fusion-011  geo-locale primary lang ≠ active_lang → score *= 0.7;
                               divergence=True; no needs_review
  orchestrator-and-fusion-012  REST Countries failure (ipapi ok, REST fail) →
                               no penalty, no needs_review
  orchestrator-and-fusion-014  lang_fallback_used (unsupported lang) → needs_review

Design contract: specs/orchestrator-and-fusion/design.md §2.2 + §4
"""

from __future__ import annotations

from pydantic import BaseModel

from app.fusion.geo import GeoContext

# ---------------------------------------------------------------------------
# Small ISO 3166-1 alpha-2 → ISO 639-1 alpha-2 map.
# Used as fallback when geo.locale is absent.  The REST Countries-derived
# locale prefix ("es" from "es-MX") is always preferred when available.
# Only covers the primary language - for req-011 we need to know whether the
# country's dominant language matches the session's active_lang.
# ---------------------------------------------------------------------------
_COUNTRY_TO_LANG: dict[str, str] = {
    # Spanish-speaking countries
    "AR": "es",
    "BO": "es",
    "CL": "es",
    "CO": "es",
    "CR": "es",
    "CU": "es",
    "DO": "es",
    "EC": "es",
    "ES": "es",
    "GQ": "es",
    "GT": "es",
    "HN": "es",
    "MX": "es",
    "NI": "es",
    "PA": "es",
    "PE": "es",
    "PR": "es",
    "PY": "es",
    "SV": "es",
    "UY": "es",
    "VE": "es",
    # Portuguese-speaking countries
    "AO": "pt",
    "BR": "pt",
    "CV": "pt",
    "GW": "pt",
    "MO": "pt",
    "MZ": "pt",
    "PT": "pt",
    "ST": "pt",
    "TL": "pt",
    # English-speaking countries
    "AU": "en",
    "BB": "en",
    "BZ": "en",
    "CA": "en",
    "FJ": "en",
    "GB": "en",
    "GH": "en",
    "GY": "en",
    "IE": "en",
    "IN": "en",
    "JM": "en",
    "KE": "en",
    "MT": "en",
    "NG": "en",
    "NZ": "en",
    "PG": "en",
    "PH": "en",
    "SG": "en",
    "TT": "en",
    "US": "en",
    "ZA": "en",
    "ZW": "en",
}


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ReconcileResult(BaseModel):
    """Output of the deterministic reconciliation step.

    Fields
    ------
    confidence_score:
        Combined confidence in the turn's signals; clamped to ``[0.0, 1.0]``.
        Starts at ``lang_confidence`` (owned by multilingual) and is damped by
        geo-error (*0.85) or locale/language divergence (*0.7).
    needs_review:
        ``True`` ONLY when ``lang_fallback_used`` is set (unsupported language
        detected).  Geo signals (error, divergence, REST-fail) DAMP the score
        but do NOT set ``needs_review`` — geo is best-effort enrichment, not a
        content-quality signal.  The orchestrator's output_validator ORs this
        with existing ``needs_review``.
    divergence:
        ``True`` when the geo-locale's primary language disagrees with
        ``active_lang``.  Subset of ``needs_review=True`` cases.

    req: orchestrator-and-fusion-007, -008, -011
    Design contract: specs/orchestrator-and-fusion/design.md §2.2 + §4
    """

    confidence_score: float
    needs_review: bool
    divergence: bool = False


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _primary_lang(geo: GeoContext) -> str | None:
    """Return the ISO-639-1 primary language for *geo*, or ``None`` if unknown.

    Prefers the REST Countries-derived locale prefix (e.g. ``"pt"`` from
    ``"pt-BR"``), which is the most authoritative signal for this country.
    Falls back to the static ``_COUNTRY_TO_LANG`` map when ``geo.locale`` is
    absent (e.g. when REST Countries enrichment was disabled or failed).

    Returns ``None`` when the language is genuinely unknown → no divergence
    penalty is applied (benefit of the doubt).

    req: orchestrator-and-fusion-011
    """
    # Prefer REST-Countries-derived locale (e.g. "es-MX" → "es").
    if geo.locale:
        parts = geo.locale.split("-")
        prefix = parts[0].lower()
        if len(prefix) == 2:  # valid ISO 639-1 length
            return prefix

    # Fallback: static country → primary-language map.
    if geo.country:
        return _COUNTRY_TO_LANG.get(str(geo.country).upper())

    return None


# ---------------------------------------------------------------------------
# Pure reconciliation function
# ---------------------------------------------------------------------------


def reconcile(
    geo: GeoContext,
    lang_confidence: float,
    active_lang: str,
    *,
    lang_fallback_used: bool,
) -> ReconcileResult:
    """Compute a ``ReconcileResult`` from fused geo + language signals.

    This is a **pure function** — no I/O, no side-effects, always returns.
    It is called by the orchestrator's ``output_validator`` after
    ``lang_confidence`` and ``active_lang`` have been set by the multilingual
    layer.  It only *reads* those values; it does not own or modify them.

    Rules (applied in order; multiple may trigger and compound):

    1. **Start**: ``score = lang_confidence`` (read-only; multilingual owns it).
       (req-007, -008)

    2. **Geo available — divergence check** (``geo.ok and geo.country``):
       Determine the country's primary language from ``geo.locale`` or the
       static map.

       - Consistent with ``active_lang`` *or* primary lang unknown → no penalty.
         High agreement → score remains high.  (req-007)
       - Divergence → ``score *= 0.7``, ``divergence=True``.
         ``needs_review`` is NOT set — expats / travellers writing in their own
         language abroad would otherwise flood review queues.  (req-011)

    3. **Geo-IP failure** (``geo.source == "error"``):
       ``score *= 0.85``.  Geo is best-effort enrichment; a flaky geo-IP API
       should not trigger human review.  ``needs_review`` is NOT set.  (req-009)

    4. **REST Countries enrichment failure** (``geo.source == "ipapi" and not
       geo.ok``):  ipapi succeeded but locale defaulted.  No score penalty,
       no ``needs_review`` — best-effort enrichment.  (req-012)

    5. **Expected / skipped sources** (``private_ip``, ``disabled``, ``cache``):
       No geo-driven penalty and no ``needs_review`` from geo.  These are
       normal operating conditions (dev environment, config flag, or cached
       prior result).  They fall through without triggering rules 2-4.
       (req-010, -015)

    6. **Unsupported language fallback** (``lang_fallback_used``):
       ``needs_review=True``.  (req-014)

    7. **Clamp** ``score`` to ``[0.0, 1.0]``.  High agreement (high
       ``lang_confidence`` + ``geo.ok`` + no divergence) → high score.
       (req-007, -008)

    Args:
        geo:               Resolved ``GeoContext`` for the request IP.
        lang_confidence:   Agreement score from the multilingual detector
                           (expected 0.0-1.0, but clamped defensively).
        active_lang:       ISO-639-1 session language (``"es"``, ``"en"``,
                           ``"pt"``).
        lang_fallback_used: ``True`` when the detected language was unsupported
                           and the session fell back to the configured fallback
                           lang.

    Returns:
        ``ReconcileResult`` with a clamped ``confidence_score``,
        ``needs_review`` flag, and ``divergence`` flag.

    req: orchestrator-and-fusion-007, -008, -009, -010, -011, -012, -014
    """
    score: float = lang_confidence
    needs_review: bool = False
    divergence: bool = False

    # Geo is OPTIONAL enrichment: its signals DAMP confidence_score but do NOT, on
    # their own, force needs_review. The reply's correctness is independent of geo —
    # flagging every geo hiccup (a flaky geo-IP API) or every geo/language mismatch
    # (expats, travellers writing in their own language abroad) would flood review
    # with false positives. needs_review stays owned by the language/guardrail layers.

    # Rule 2: geo resolved → a country-primary-language vs active_lang mismatch DAMPS
    # confidence (weak divergence signal), no review. req-007 (agreement→no penalty),
    # req-011 (divergence damps confidence).
    if geo.ok and geo.country:
        primary_lang = _primary_lang(geo)
        if primary_lang is not None and primary_lang != active_lang.lower():
            divergence = True
            score *= 0.7

    # Rule 3: geo-IP lookup failed (source=="error") → damp confidence; no review,
    # since geo is best-effort enrichment, not a content/answer signal. req-009.
    if geo.source == "error":
        score *= 0.85

    # Rule 4: ipapi ok but REST Countries enrichment failed (source=="ipapi", not ok)
    # → locale/timezone defaulted; no penalty, no review (best-effort). req-012.

    # Rule 5: private_ip / disabled / cache → no geo-driven penalty, no review (normal
    # operating conditions). req-010, -015, -017.

    # Rule 6: unsupported-language fallback IS a genuine language problem (not a geo
    # signal) → flag review (the multilingual layer also sets this). req-014.
    if lang_fallback_used:
        needs_review = True

    # Rule 7: clamp score to [0.0, 1.0].
    # req-007, -008
    score = max(0.0, min(1.0, score))

    return ReconcileResult(
        confidence_score=score,
        needs_review=needs_review,
        divergence=divergence,
    )
