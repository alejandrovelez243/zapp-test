"""Unit tests for GeoFusionService (app/fusion/geo.py).

All httpx I/O is intercepted by a hand-rolled _FakeHttp that records every URL
seen and returns pre-canned payloads or raises canned exceptions.  No real
network calls are made; the suite is fully offline and deterministic.

Requirement traceability:
  orchestrator-and-fusion-002  ipapi.co geo-IP lookup resolves country + timezone
  orchestrator-and-fusion-004  REST Countries enriches locale (spa → es-MX)
  orchestrator-and-fusion-009  ipapi error / timeout / no-country → source="error", ok=False
  orchestrator-and-fusion-010  private / loopback / invalid IP → source="private_ip", no call
  orchestrator-and-fusion-012  REST Countries failure → country set, default locale, ok=False
  orchestrator-and-fusion-015  geo_fusion_enabled=False → source="disabled", no call
  orchestrator-and-fusion-016  rest_countries_enabled=False → default locale, no RC call
  orchestrator-and-fusion-017  per-IP dict cache → second resolve → source="cache", no new call
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.fusion.geo import GeoContext, GeoFusionService

# ---------------------------------------------------------------------------
# Canonical test data
# ---------------------------------------------------------------------------

_DEFAULT_LOCALE = "en-US"
_DEFAULT_TZ = "UTC"

# ipapi.co payload for a Mexican public IP.
_IPAPI_MX: dict[str, object] = {
    "country_code": "MX",
    "timezone": "America/Mexico_City",
}

# REST Countries payload for Mexico — languages dict uses ISO 639-2 alpha-3 keys.
_RC_MX: list[dict[str, object]] = [
    {
        "cca2": "MX",
        "languages": {"spa": "Spanish"},
        "timezones": ["America/Mexico_City"],
    }
]

# Public IP used for tests that should hit the network path.
_PUBLIC_IP = "189.16.0.1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> SimpleNamespace:
    """Return a SimpleNamespace satisfying the _GeoSettings protocol."""
    base: dict[str, object] = {
        "geo_fusion_enabled": True,
        "rest_countries_enabled": True,
        "ipapi_base_url": "https://ipapi.co",
        "rest_countries_base_url": "https://restcountries.com/v3.1",
        "geo_timeout": 3.0,
        "default_locale": _DEFAULT_LOCALE,
        "default_timezone": _DEFAULT_TZ,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeHttp:
    """Hand-rolled fake for httpx.AsyncClient — fully offline.

    Dispatches .get() calls by URL substring:
      - "ipapi.co"        → ipapi branch (ipapi_payload or raise ipapi_exc)
      - "restcountries"   → REST Countries branch (rc_payload or raise rc_exc)

    call_urls records every URL passed to .get() so tests can assert
    "no network call was made" by checking len(call_urls) == 0.
    """

    def __init__(
        self,
        ipapi_payload: dict[str, object] | None = None,
        ipapi_exc: BaseException | None = None,
        rc_payload: list[dict[str, object]] | None = None,
        rc_exc: BaseException | None = None,
    ) -> None:
        self._ipapi_payload = ipapi_payload
        self._ipapi_exc = ipapi_exc
        self._rc_payload = rc_payload
        self._rc_exc = rc_exc
        self.call_urls: list[str] = []

    async def get(self, url: str, **_kwargs: object) -> httpx.Response:
        self.call_urls.append(url)
        # httpx >=0.27 requires a request instance on Response so that
        # raise_for_status() does not raise RuntimeError even on 2xx codes.
        req = httpx.Request("GET", url)
        if "ipapi.co" in url:
            if self._ipapi_exc is not None:
                raise self._ipapi_exc
            if self._ipapi_payload is None:
                raise httpx.ConnectError("ipapi not configured in fake")
            return httpx.Response(200, json=self._ipapi_payload, request=req)
        # REST Countries branch
        if self._rc_exc is not None:
            raise self._rc_exc
        if self._rc_payload is None:
            raise httpx.ConnectError("REST Countries not configured in fake")
        return httpx.Response(200, json=self._rc_payload, request=req)


def _svc(
    http: _FakeHttp,
    **settings_overrides: object,
) -> GeoFusionService:
    """Construct a GeoFusionService with a fake HTTP client."""
    return GeoFusionService(
        http=http,  # type: ignore[arg-type]
        settings=_make_settings(**settings_overrides),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGeoFusionService:
    """Unit-test every GeoContext source branch and error path.

    Uses _FakeHttp — zero real network calls, deterministic, offline.
    """

    # ------------------------------------------------------------------
    # Happy path: full ipapi → REST Countries resolve (req-002, -004)
    # ------------------------------------------------------------------

    async def test_full_resolve_ipapi_and_rest_countries(self) -> None:
        """ipapi + REST Countries both succeed → country/timezone/locale set, ok=True.

        req: orchestrator-and-fusion-002 — ipapi.co lookup resolves country
        req: orchestrator-and-fusion-004 — REST Countries enriches locale (spa → es-MX)
        """
        http = _FakeHttp(ipapi_payload=_IPAPI_MX, rc_payload=_RC_MX)
        geo = await _svc(http).resolve(_PUBLIC_IP)

        assert str(geo.country) == "MX", f"Expected country='MX', got {geo.country!r}"
        assert geo.timezone == "America/Mexico_City"
        assert geo.locale == "es-MX", f"Expected locale='es-MX', got {geo.locale!r}"
        assert geo.source == "ipapi"
        assert geo.ok is True
        # Both ipapi and REST Countries were called (req-002, -004).
        assert any("ipapi.co" in u for u in http.call_urls), "ipapi.co not called"
        assert any("restcountries" in u for u in http.call_urls), "REST Countries not called"

    # ------------------------------------------------------------------
    # geo_fusion_enabled=False → source="disabled", no network call (req-015)
    # ------------------------------------------------------------------

    async def test_geo_fusion_disabled_returns_disabled_source(self) -> None:
        """geo_fusion_enabled=False → GeoContext(source="disabled"), zero network calls.

        req: orchestrator-and-fusion-015
        """
        http = _FakeHttp()  # no payloads — any call would raise
        geo = await _svc(http, geo_fusion_enabled=False).resolve(_PUBLIC_IP)

        assert geo.source == "disabled"
        assert geo.country is None
        assert geo.ok is False
        assert len(http.call_urls) == 0, "No network call expected when geo_fusion_enabled=False"

    # ------------------------------------------------------------------
    # Private / loopback / invalid IPs → source="private_ip" (req-010)
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "ip",
        [
            "192.168.1.100",  # RFC-1918 private
            "10.0.0.1",  # RFC-1918 private
            "172.16.5.1",  # RFC-1918 private
            "127.0.0.1",  # loopback
            "::1",  # IPv6 loopback
            "169.254.1.1",  # link-local
            "not-an-ip",  # malformed string
            "",  # empty string
        ],
    )
    async def test_private_or_invalid_ip_no_network_call(self, ip: str) -> None:
        """Private / loopback / invalid IPs → source="private_ip", no external call.

        req: orchestrator-and-fusion-010
        """
        http = _FakeHttp()
        geo = await _svc(http).resolve(ip)

        assert geo.source == "private_ip", f"Expected source='private_ip' for ip={ip!r}"
        assert geo.country is None
        assert geo.ok is False
        assert len(http.call_urls) == 0, f"No network call expected for ip={ip!r}"

    # ------------------------------------------------------------------
    # ipapi error → source="error", ok=False (req-009)
    # ------------------------------------------------------------------

    async def test_ipapi_http_error_returns_error_context(self) -> None:
        """ipapi raises HTTPError → source="error", country=None, ok=False.

        req: orchestrator-and-fusion-009
        """
        http = _FakeHttp(ipapi_exc=httpx.ConnectError("connection refused"))
        geo = await _svc(http).resolve(_PUBLIC_IP)

        assert geo.source == "error"
        assert geo.country is None
        assert geo.ok is False

    async def test_ipapi_timeout_returns_error_context(self) -> None:
        """ipapi raises ReadTimeout → source="error", ok=False.

        req: orchestrator-and-fusion-009
        """
        http = _FakeHttp(ipapi_exc=httpx.ReadTimeout("timed out"))
        geo = await _svc(http).resolve(_PUBLIC_IP)

        assert geo.source == "error"
        assert geo.country is None
        assert geo.ok is False

    async def test_ipapi_no_country_in_payload_returns_error(self) -> None:
        """ipapi returns 200 but payload has no country_code/country → source="error".

        req: orchestrator-and-fusion-009
        """
        http = _FakeHttp(ipapi_payload={"ip": _PUBLIC_IP, "timezone": "UTC"})
        geo = await _svc(http).resolve(_PUBLIC_IP)

        assert geo.source == "error"
        assert geo.country is None
        assert geo.ok is False

    async def test_ipapi_generic_exception_returns_error(self) -> None:
        """Any unhandled exception from ipapi → source="error", ok=False.

        req: orchestrator-and-fusion-009
        """
        http = _FakeHttp(ipapi_exc=RuntimeError("unexpected"))
        geo = await _svc(http).resolve(_PUBLIC_IP)

        assert geo.source == "error"
        assert geo.ok is False

    # ------------------------------------------------------------------
    # REST Countries failure → partial ok=False, country still set (req-012)
    # ------------------------------------------------------------------

    async def test_rest_countries_failure_country_set_locale_default(self) -> None:
        """ipapi succeeds, REST Countries raises → country set, default locale, ok=False.

        req: orchestrator-and-fusion-012
        """
        http = _FakeHttp(
            ipapi_payload=_IPAPI_MX,
            rc_exc=httpx.ConnectError("REST Countries down"),
        )
        geo = await _svc(http).resolve(_PUBLIC_IP)

        assert geo.source == "ipapi"
        assert str(geo.country) == "MX", f"country should still be set; got {geo.country!r}"
        assert geo.locale == _DEFAULT_LOCALE, (
            f"Expected default locale={_DEFAULT_LOCALE!r}, got {geo.locale!r}"
        )
        assert geo.ok is False, "ok must be False when REST Countries enrichment failed"

    async def test_rest_countries_empty_list_uses_default_locale(self) -> None:
        """REST Countries returns an empty list → graceful fallback to default locale.

        req: orchestrator-and-fusion-012
        """
        http = _FakeHttp(ipapi_payload=_IPAPI_MX, rc_payload=[])
        geo = await _svc(http).resolve(_PUBLIC_IP)

        assert geo.source == "ipapi"
        assert str(geo.country) == "MX"
        assert geo.locale == _DEFAULT_LOCALE
        assert geo.ok is False

    # ------------------------------------------------------------------
    # rest_countries_enabled=False → default locale, no RC call (req-016)
    # ------------------------------------------------------------------

    async def test_rest_countries_disabled_uses_default_locale_no_rc_call(self) -> None:
        """rest_countries_enabled=False → locale=default_locale, no REST Countries call.

        req: orchestrator-and-fusion-016
        """
        http = _FakeHttp(ipapi_payload=_IPAPI_MX)  # rc_payload not set → call would raise
        geo = await _svc(http, rest_countries_enabled=False).resolve(_PUBLIC_IP)

        assert geo.source == "ipapi"
        assert str(geo.country) == "MX"
        assert geo.locale == _DEFAULT_LOCALE, (
            f"Expected default locale when RC disabled; got {geo.locale!r}"
        )
        # RC was disabled — no restcountries URL should appear in call log.
        assert not any("restcountries" in u for u in http.call_urls), (
            "REST Countries should NOT be called when rest_countries_enabled=False"
        )

    # ------------------------------------------------------------------
    # Per-IP cache → second resolve returns source="cache" (req-017)
    # ------------------------------------------------------------------

    async def test_per_ip_cache_returns_cache_source_on_second_call(self) -> None:
        """Same IP resolved twice: first→source="ipapi", second→source="cache", no new call.

        req: orchestrator-and-fusion-017
        """
        http = _FakeHttp(ipapi_payload=_IPAPI_MX, rc_payload=_RC_MX)
        svc = _svc(http)

        geo1 = await svc.resolve(_PUBLIC_IP)
        call_count_after_first = len(http.call_urls)

        geo2 = await svc.resolve(_PUBLIC_IP)
        call_count_after_second = len(http.call_urls)

        # First call goes to network.
        assert geo1.source == "ipapi"
        assert str(geo1.country) == "MX"
        assert geo1.ok is True

        # Second call served from cache — no additional network calls.
        assert geo2.source == "cache", (
            f"Expected source='cache' on second resolve, got {geo2.source!r}"
        )
        assert str(geo2.country) == "MX"
        assert geo2.ok is True
        assert call_count_after_second == call_count_after_first, (
            f"No extra network calls expected on cache hit; "
            f"first={call_count_after_first}, second={call_count_after_second}"
        )

    # ------------------------------------------------------------------
    # resolve() NEVER raises on any failure (req-009, req-013)
    # ------------------------------------------------------------------

    async def test_resolve_never_raises_on_ipapi_failure(self) -> None:
        """resolve() must not propagate any exception — always returns GeoContext.

        req: orchestrator-and-fusion-009 — error → GeoContext(source="error")
        req: orchestrator-and-fusion-013 — NEVER raises to the caller
        """
        http = _FakeHttp(ipapi_exc=RuntimeError("catastrophic failure"))
        # Must not raise — any exception here is a test failure.
        geo = await _svc(http).resolve(_PUBLIC_IP)
        assert isinstance(geo, GeoContext)

    async def test_resolve_never_raises_on_broken_payload(self) -> None:
        """resolve() with a completely wrong payload type still returns GeoContext safely.

        req: orchestrator-and-fusion-013
        """
        # A non-dict payload (e.g. a list) — resp.json() returns a list, then
        # data.get(...) raises AttributeError, caught by the outer except.
        http = _FakeHttp(ipapi_payload={"country_code": "ZZ"})  # invalid ISO code
        geo = await _svc(http).resolve(_PUBLIC_IP)
        assert isinstance(geo, GeoContext)
        # "ZZ" is not a valid CountryAlpha2 code — should fall to source="error".
        assert geo.source == "error"

    # ------------------------------------------------------------------
    # req-017: error results must NOT be cached (transient failure fix)
    # ------------------------------------------------------------------

    async def test_error_result_is_not_cached(self) -> None:
        """source="error" results must NOT populate the cache.

        A transient ipapi.co failure (timeout, 5xx) on the first call must not
        make that failure sticky.  A subsequent call with a working backend must
        return source="ipapi" (fresh network call), not source="cache".

        req: orchestrator-and-fusion-017 — only successful resolutions are cached
        """
        # First call: ipapi raises → source="error"
        http_fail = _FakeHttp(ipapi_exc=httpx.ConnectError("transient failure"))
        svc = _svc(http_fail)

        geo_fail = await svc.resolve(_PUBLIC_IP)
        assert geo_fail.source == "error"

        # Cache must be empty — error result was NOT stored.
        assert _PUBLIC_IP not in svc._cache, "source='error' result must not be stored in the cache"

        # Second call on the SAME service instance with a working HTTP client.
        # We swap the internal client to simulate recovery.
        svc._http = _FakeHttp(ipapi_payload=_IPAPI_MX, rc_payload=_RC_MX)  # type: ignore[assignment]
        geo_ok = await svc.resolve(_PUBLIC_IP)

        # Fresh network call succeeds — NOT a stale cache entry.
        assert geo_ok.source == "ipapi", (
            f"Expected 'ipapi' on recovered call, got {geo_ok.source!r}"
        )
        assert str(geo_ok.country) == "MX"
        assert geo_ok.ok is True
