"""Smoke test: run_turn wires GeoFusionService geo resolution into AgentDeps so that
detected_country flows through the orchestrator output_validator (_reconcile_fusion) and
appears in the final TurnOutput contract dict.

This test verifies Task 7 of orchestrator-and-fusion: mirror geo resolution in
evals/task.py run_turn.  It uses:
  - unittest.mock.AsyncMock to stub GeoFusionService.resolve (no real network call).
  - TestModel to stub the orchestrator (no real LLM call / API key needed).

Requirements:
  orchestrator-and-fusion-001 — detected_country populated on every turn's contract.
  orchestrator-and-fusion-002 — geo-IP resolution runs on the request IP in run_turn.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from app.agents.orchestrator import get_orchestrator
from app.fusion.geo import GeoContext
from evals.task import run_turn

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Minimal valid TurnOutput payload for TestModel — all nine contract fields present.
# The output_validator (_reconcile_fusion) will OVERWRITE detected_country with
# deps.geo.country (code-set, never LLM-set), so the initial None here is fine.
_VALID_TURN_ARGS: dict[str, object] = {
    "reply": "¡Hola! Ofrecemos cursos de filosofía en español, inglés y portugués.",
    "detected_lang": "es",
    "active_lang": "es",
    "lang_confidence": 0.9,
    "final_normalized_text": "¿Qué cursos hay?",
    "detected_country": None,  # _reconcile_fusion overwrites this from deps.geo.country
    "confidence_score": 0.9,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}

# GeoContext returned by the mocked resolve — MX country, enrichment succeeded.
_GEO_MX = GeoContext(country="MX", ok=True, source="ipapi", locale="es-MX")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunTurnGeoWiring:
    """Verify geo resolution is wired into run_turn and detected_country flows through.

    req: orchestrator-and-fusion-001, orchestrator-and-fusion-002
    """

    async def test_detected_country_flows_from_geo_to_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_turn with mocked GeoFusionService.resolve(MX) yields detected_country='MX'.

        Flow:
          1. GeoFusionService.resolve is mocked → returns GeoContext(country='MX', ...).
          2. run_turn builds AgentDeps(geo=<mocked GeoContext>).
          3. Orchestrator (TestModel) runs and the output_validator _reconcile_fusion
             sets output.detected_country = deps.geo.country = 'MX' (code-set, not LLM).
          4. model_dump() serialises CountryAlpha2('MX') → 'MX' string.
          5. Assertion: out["detected_country"] == 'MX'.

        req: orchestrator-and-fusion-001
        """
        # Required Settings fields (no DB access in run_turn; sqlite URL is a safe stub).
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")

        # Patch GeoFusionService.resolve at the class level so the instance created
        # inside run_turn returns the mocked GeoContext without any network call.
        with (
            patch(
                "app.fusion.geo.GeoFusionService.resolve",
                new_callable=AsyncMock,
                return_value=_GEO_MX,
            ),
            get_orchestrator().override(model=TestModel(custom_output_args=_VALID_TURN_ARGS)),
        ):
            out = await run_turn({"message": "¿Qué cursos hay?", "ip": "189.0.0.1"})

        # The _reconcile_fusion output_validator copies deps.geo.country → detected_country.
        # CountryAlpha2 is a str subclass; model_dump() serialises it as the 2-char string.
        assert out["detected_country"] == "MX", (
            f"Expected detected_country='MX', got {out['detected_country']!r}. "
            "GeoFusionService.resolve mock may not have been picked up by run_turn, "
            "or _reconcile_fusion did not set detected_country from deps.geo.country."
        )
        print("OK")
