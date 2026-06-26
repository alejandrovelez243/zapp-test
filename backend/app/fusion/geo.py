"""Geo-IP fusion service — resolves country, timezone, and locale for a request IP.

Calls **ipapi.co** (keyless) for country/timezone/languages, then optionally enriches
the locale variant (pt-BR vs pt-PT, es-MX vs es-ES) via **REST Countries**.  All
network work is wrapped in a ``logfire.span("geo_fusion")`` so it shows as one
traceable span in Logfire (the outbound ``httpx`` calls are already instrumented
globally via ``logfire.instrument_httpx``).

Requirement traceability:
  orchestrator-and-fusion-002  ipapi.co geo-IP lookup
  orchestrator-and-fusion-003  logfire.span("geo_fusion") wrapping all network work
  orchestrator-and-fusion-004  REST Countries locale enrichment (lang3 -> lang2-CC)
  orchestrator-and-fusion-009  ipapi error / timeout / bad payload -> source="error", ok=False
  orchestrator-and-fusion-010  private/loopback/invalid IP short-circuit -> source="private_ip"
  orchestrator-and-fusion-012  REST Countries failure -> default_locale, ok=False (partial)
  orchestrator-and-fusion-015  geo_fusion_enabled=False -> source="disabled" (no network call)
  orchestrator-and-fusion-016  rest_countries_enabled=False -> default_locale, no RC call
  orchestrator-and-fusion-017  per-IP dict cache (process-level LRU) -> source="cache"

Design contract: specs/orchestrator-and-fusion/design.md §2.1 + §4
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any, Literal, Protocol

import httpx
import logfire
from pydantic import BaseModel, ValidationError
from pydantic_extra_types.country import CountryAlpha2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ISO 639-2 alpha-3 -> ISO 639-1 alpha-2 for the most common language codes.
# REST Countries uses alpha-3 keys in its ``languages`` dict.
# ---------------------------------------------------------------------------
_LANG3_TO_LANG2: dict[str, str] = {
    "spa": "es",
    "por": "pt",
    "eng": "en",
    "fra": "fr",
    "deu": "de",
    "nld": "nl",
    "ita": "it",
    "rus": "ru",
    "zho": "zh",
    "ara": "ar",
    "jpn": "ja",
    "kor": "ko",
    "cat": "ca",
    "glg": "gl",
    "eus": "eu",
}


# ---------------------------------------------------------------------------
# Settings protocol
# ---------------------------------------------------------------------------


class _GeoSettings(Protocol):
    """Structural interface for the Settings fields consumed by GeoFusionService.

    Using a Protocol (rather than the concrete Settings class) lets this module
    be type-checked correctly before Task 1 adds the new fields to ``app/config.py``
    Settings, and also allows SimpleNamespace stubs in smoke/unit tests.

    req: orchestrator-and-fusion-015, -016 (flag fields)
    """

    geo_fusion_enabled: bool
    rest_countries_enabled: bool
    ipapi_base_url: str
    rest_countries_base_url: str
    geo_timeout: float
    default_locale: str
    default_timezone: str


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class GeoContext(BaseModel):
    """Resolved geo context for a single request IP.

    Fields
    ------
    country:
        ISO 3166-1 alpha-2 country code (e.g. ``"MX"``), or ``None`` when the
        lookup was skipped or failed.
    timezone:
        IANA timezone string (e.g. ``"America/Mexico_City"``), or ``None``.
    locale:
        BCP-47 locale tag (e.g. ``"pt-BR"``), or ``None``.
    source:
        How this result was produced:
        - ``"ipapi"``      — full ipapi.co lookup succeeded (REST Countries may or may
                            not have been called; check ``ok`` for enrichment status).
        - ``"cache"``      — returned from the per-IP process cache (req-017).
        - ``"disabled"``   — ``geo_fusion_enabled=False``; no network call (req-015).
        - ``"private_ip"`` — IP was private/loopback/invalid; no network call (req-010).
        - ``"error"``      — ipapi.co call failed; ``country`` is ``None`` (req-009).
    ok:
        ``True`` when the country is authoritatively resolved.
        ``False`` on any failure:
        - source=``"error"`` or ``"disabled"`` or ``"private_ip"`` -> ok=False (expected).
        - source=``"ipapi"`` + ok=False -> ipapi succeeded but REST Countries failed
          (req-012); ``country`` is still set, ``locale`` is the configured default.

    req: orchestrator-and-fusion-002, -004, -009, -010, -015, -016, -017
    Design contract: specs/orchestrator-and-fusion/design.md §4
    """

    country: CountryAlpha2 | None = None
    timezone: str | None = None
    locale: str | None = None
    source: Literal["ipapi", "cache", "disabled", "private_ip", "error"] = "error"
    ok: bool = False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GeoFusionService:
    """Resolves geo context for a request IP via ipapi.co + REST Countries.

    All network work executes inside a ``logfire.span("geo_fusion")`` span so the
    two outbound HTTP calls appear as one traceable unit in Logfire alongside the
    ``httpx`` spans emitted by ``logfire.instrument_httpx``.

    This class is **instantiated per-request** (or per test run) and holds a
    process-level dict cache that survives across calls when the same instance is
    reused (e.g. injected as a singleton via ``AgentDeps``).  The cache is keyed
    by IP string; no TTL is applied in this implementation (revisit on horizontal
    scaling — see design.md §6).

    Args:
        http:     Shared ``httpx.AsyncClient`` (already instrumented by Logfire).
        settings: Settings object (or any object satisfying ``_GeoSettings``).

    req: orchestrator-and-fusion-002..004, -009, -010, -012, -015..017
    """

    def __init__(self, http: httpx.AsyncClient, settings: _GeoSettings) -> None:
        self._http = http
        self._settings = settings
        # req-017: per-IP dict cache (process-level; keyed by IP string).
        self._cache: dict[str, GeoContext] = {}

    async def resolve(self, ip: str) -> GeoContext:
        """Resolve the geo context for *ip*.

        This method NEVER raises.  Any unhandled error inside the implementation
        returns ``GeoContext(source="error", ok=False)`` so the calling boundary
        always receives a valid ``GeoContext`` regardless of external-API health.

        Resolution order:
        1. ``geo_fusion_enabled=False`` -> ``source="disabled"`` (no network). (req-015)
        2. Private / loopback / invalid IP -> ``source="private_ip"`` (no network). (req-010)
        3. Per-IP cache hit -> ``source="cache"``. (req-017)
        4. ipapi.co lookup + optional REST Countries enrichment inside a Logfire span.
           (req-002..004)
        5. Any failure in step 4 -> ``source="error"`` or partial ok=False. (req-009, -012)
        """
        # req-015: master geo flag
        if not self._settings.geo_fusion_enabled:
            return GeoContext(source="disabled")

        # req-010: private/loopback/invalid IP — skip external call
        if _is_private_or_invalid(ip):
            return GeoContext(source="private_ip")

        # req-017: process-level per-IP cache
        if ip in self._cache:
            cached = self._cache[ip]
            # Return a cache-sourced copy so callers see source="cache".
            return GeoContext(
                country=cached.country,
                timezone=cached.timezone,
                locale=cached.locale,
                source="cache",
                ok=cached.ok,
            )

        # req-003: wrap all network work in a single Logfire span.
        with logfire.span("geo_fusion", ip=ip):
            result = await self._fetch_and_enrich(ip)

        # req-017: only cache determinate (non-error) results.  source="error"
        # is typically transient (flaky API, timeout) — caching it would make a
        # temporary failure sticky across the process lifetime.  source="ipapi"
        # (ok=True or ok=False) is cacheable because the country/timezone are
        # authoritative even when REST Countries enrichment failed.
        if result.source != "error":
            self._cache[ip] = result
        return result

    async def _fetch_and_enrich(self, ip: str) -> GeoContext:
        """Call ipapi.co then (optionally) REST Countries.  NEVER raises.

        Returns ``GeoContext(source="error", ok=False)`` for any ipapi failure.
        Returns ``GeoContext(source="ipapi", ok=False, ...)`` when ipapi succeeds
        but REST Countries fails (req-012): country and timezone are still set; locale
        falls back to ``settings.default_locale``.

        req: orchestrator-and-fusion-002, -004, -009, -012, -016
        """
        try:
            # req-002: GET {ipapi_base_url}/{ip}/json/
            ipapi_url = f"{self._settings.ipapi_base_url}/{ip}/json/"
            resp = await self._http.get(ipapi_url, timeout=self._settings.geo_timeout)
            resp.raise_for_status()

            data: dict[str, Any] = resp.json()

            # ipapi.co uses "country_code" (fallback: "country") for the alpha-2 code.
            raw_cc: str | None = data.get("country_code") or data.get("country")
            if not raw_cc:
                # req-009: no country in response counts as a geo failure.
                logger.debug("geo_fusion: ipapi returned no country for ip=%s", ip)
                return GeoContext(source="error", ok=False)

            cc: str = str(raw_cc).upper().strip()[:2]
            timezone: str | None = data.get("timezone") or self._settings.default_timezone

            # req-004 / req-016: enrich locale via REST Countries, or fall back.
            locale, rc_ok = await self._resolve_locale(cc)

            try:
                # Pydantic validates cc as a valid ISO 3166-1 alpha-2 code.
                country = CountryAlpha2(cc)
            except (ValidationError, Exception):
                # Invalid country code from ipapi -> treat as geo error.
                logger.debug("geo_fusion: invalid country code %r for ip=%s", cc, ip)
                return GeoContext(source="error", ok=False)

            # ok=True only when BOTH ipapi AND REST Countries (when enabled) succeeded.
            # ok=False with source="ipapi" signals req-012 (partial: country is known,
            # locale fell back to default) so reconcile can apply the right damping.
            return GeoContext(
                country=country,
                timezone=timezone,
                locale=locale,
                source="ipapi",
                ok=rc_ok,
            )

        except Exception:
            # req-009, -013: NEVER propagate; any unhandled error -> error context.
            logger.debug("geo_fusion: ipapi lookup failed for ip=%s", ip, exc_info=True)
            return GeoContext(source="error", ok=False)

    async def _resolve_locale(self, cc: str) -> tuple[str, bool]:
        """Return ``(locale, ok)`` for *cc* using REST Countries or the default.

        ``ok`` is ``True`` only when REST Countries was enabled AND the call succeeded.

        req: orchestrator-and-fusion-004, -012, -016
        """
        if not self._settings.rest_countries_enabled:
            # req-016: config flag disables enrichment; use default locale, no error.
            return self._settings.default_locale, True

        # req-004: enrich locale via REST Countries.
        try:
            rc_url = f"{self._settings.rest_countries_base_url}/alpha/{cc}"
            resp = await self._http.get(rc_url, timeout=self._settings.geo_timeout)
            resp.raise_for_status()

            rc_data: list[Any] = resp.json()
            if not rc_data or not isinstance(rc_data, list):
                # Unexpected payload shape -> fall back gracefully.
                logger.debug("geo_fusion: REST Countries unexpected payload for cc=%s", cc)
                return self._settings.default_locale, False

            country_obj: dict[str, Any] = rc_data[0]
            languages_dict: dict[str, str] = country_obj.get("languages", {})

            if languages_dict:
                # languages dict: ISO 639-2 alpha-3 -> display name.
                # Take the first key and map to ISO 639-1 alpha-2.
                first_lang3: str = next(iter(languages_dict))
                lang2: str | None = _LANG3_TO_LANG2.get(first_lang3)
                if lang2:
                    return f"{lang2}-{cc}", True

            # REST Countries returned no usable language data.
            logger.debug("geo_fusion: no languages in REST Countries response for cc=%s", cc)
            return self._settings.default_locale, False

        except Exception:
            # req-012: REST Countries enrichment failed -> default locale, ok=False.
            logger.debug("geo_fusion: REST Countries lookup failed for cc=%s", cc, exc_info=True)
            return self._settings.default_locale, False


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _is_private_or_invalid(ip: str) -> bool:
    """Return ``True`` for private, loopback, link-local, unspecified, or invalid IPs.

    Invalid IP strings (``ValueError`` from ``ipaddress``) are treated as private to
    prevent external calls for malformed input.

    req: orchestrator-and-fusion-010
    """
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified
    except ValueError:
        return True  # malformed IP string -> treat as private/invalid
