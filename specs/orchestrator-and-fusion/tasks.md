# Orchestrator & Signal-Fusion Tasks

Ordered, dependency-aware plan for `orchestrator-and-fusion` (geo-IP + REST Countries fusion →
`detected_country`/`final_normalized_text`/`confidence_score`, deterministic reconciliation in the
output_validator). Each task = one specialist delegation + one commit. Traceability:
`— _req: <ids> — owner: <specialist>_`. Prereqs (config, models, service, reconcile, deps) precede the
orchestrator/boundary wiring. Drive task-by-task via `/implement orchestrator-and-fusion`.

> Two external APIs over the shared `httpx` client (instrumented): **ipapi.co** (keyless geo-IP) +
> **REST Countries** (locale/timezone). `detected_country` + `confidence_score` are set by CODE
> (validator); the LLM only authors `final_normalized_text`. Geo runs deterministically at the boundary
> inside `logfire.span("geo_fusion")` (req-003). Real eval run (task 10) needs `PYDANTIC_AI_GATEWAY_API_KEY`.

## Tasks

- [ ] 1. Add fusion config to `app/config.py` `Settings`: `geo_fusion_enabled: bool = True`, `rest_countries_enabled: bool = True`, `ipapi_base_url`, `rest_countries_base_url`, `geo_timeout: float = 3.0`, `default_locale`, `default_timezone`. — _req: orchestrator-and-fusion-015, orchestrator-and-fusion-016 — owner: backend-engineer_

- [ ] 2. Implement `app/fusion/geo.py` — `GeoContext` (Pydantic: country/timezone/locale/source/ok) + `GeoFusionService(http, settings).resolve(ip)`: ipapi.co lookup → REST Countries locale enrichment, wrapped in `logfire.span("geo_fusion")` (calls go through the instrumented `httpx`), timeout-bounded, per-IP LRU cache, private/loopback/invalid-IP short-circuit, `geo_fusion_enabled`/`rest_countries_enabled` gates, default-locale fallback; NEVER raises (errors → `source="error"`, `ok=False`, `country=None`). — _req: orchestrator-and-fusion-002, orchestrator-and-fusion-003, orchestrator-and-fusion-004, orchestrator-and-fusion-009, orchestrator-and-fusion-010, orchestrator-and-fusion-012, orchestrator-and-fusion-015, orchestrator-and-fusion-016, orchestrator-and-fusion-017 — owner: backend-engineer_

- [ ] 3. Implement `app/fusion/reconcile.py` — pure `reconcile(geo, lang_confidence, active_lang, detection, lang_fallback_used) -> ReconcileResult` (confidence_score, needs_review, divergence): start from `lang_confidence`; high on agreement+geo-ok+no-divergence; damp+review on geo-error, on locale↔active_lang divergence, on REST fallback; no penalty for private_ip/disabled; review on unsupported-language fallback; clamp [0,1]. — _req: orchestrator-and-fusion-007, orchestrator-and-fusion-008, orchestrator-and-fusion-009, orchestrator-and-fusion-010, orchestrator-and-fusion-011, orchestrator-and-fusion-012, orchestrator-and-fusion-014 — owner: backend-engineer_

- [ ] 4. Add `geo: GeoContext` to `AgentDeps` in `app/deps.py` (carry the resolved geo into the run). — _req: orchestrator-and-fusion-001 — owner: backend-engineer_

- [ ] 5. Wire the orchestrator (`app/agents/orchestrator.py`): a dynamic `@instructions` injecting `geo.locale` + `geo.timezone` + a "now" so the LLM sets `final_normalized_text` (cleaned text + relative dates resolved to the timezone, in `active_lang`); extend the `output_validator` (`_reconcile_fusion`, guard `partial_output`) to set `detected_country = deps.geo.country`, call `reconcile(...)` → set `confidence_score` + OR `needs_review`, and fall back `final_normalized_text` to the raw message if empty. — _req: orchestrator-and-fusion-001, orchestrator-and-fusion-005, orchestrator-and-fusion-006, orchestrator-and-fusion-008, orchestrator-and-fusion-013, orchestrator-and-fusion-014 — owner: backend-engineer_

- [ ] 6. Wire `app/api/chat.py`: after input guardrails, `geo = await GeoFusionService(http, settings).resolve(request_ip)`; build `AgentDeps(..., geo=geo)`; ensure the degrade path also carries `geo` so a degraded turn still reports `detected_country`. — _req: orchestrator-and-fusion-002, orchestrator-and-fusion-013 — owner: backend-engineer_

- [ ] 7. Mirror geo resolution in `backend/evals/task.py` `run_turn` (resolve geo, attach to deps) so eval Cases populate `detected_country`/`confidence_score`; allow an injectable fixed "now" for criterion-006 determinism. — _req: orchestrator-and-fusion-001, orchestrator-and-fusion-006 — owner: eval-engineer_

- [ ] 8. Add geo/fusion eval Cases (`backend/evals/datasets/`): happy (country+locale resolved, high confidence), divergence (geo locale ≠ active_lang → needs_review), geo-failure (null country → needs_review), private-IP (null country, no review), and a relative-date-resolution case with a fixed "now". — _req: orchestrator-and-fusion-001..orchestrator-and-fusion-017 (eval coverage) — owner: eval-engineer_

- [ ] 9. Add tests: `GeoFusionService` (ipapi+REST via mocked httpx, private-IP, flags off, cache reuse, error→null, never-raises), `reconcile` (every branch), the orchestrator `_reconcile_fusion` validator (sets the 3 fields + needs_review via TestModel), and the `/chat` boundary (geo attached + degrade carries geo). — _req: orchestrator-and-fusion-001..orchestrator-and-fusion-017 — owner: backend-engineer_

- [ ] 10. Eval verification: run the suite so `detected_country`/`confidence_score` populate and the fusion Cases pass; tune rules/dataset if needed. (Real run needs `PYDANTIC_AI_GATEWAY_API_KEY`; the deterministic geo/reconcile logic is unit-verifiable without it.) — _req: orchestrator-and-fusion-001..orchestrator-and-fusion-017 — owner: eval-engineer_

## Coverage

| Req | Tasks |
|---|---|
| orchestrator-and-fusion-001 | 4, 5, 8, 9 |
| orchestrator-and-fusion-002 | 2, 6, 9 |
| orchestrator-and-fusion-003 | 2, 9 |
| orchestrator-and-fusion-004 | 2, 9 |
| orchestrator-and-fusion-005 | 5, 9 |
| orchestrator-and-fusion-006 | 5, 7, 8, 9 |
| orchestrator-and-fusion-007 | 3, 9 |
| orchestrator-and-fusion-008 | 3, 5, 9 |
| orchestrator-and-fusion-009 | 2, 3, 9 |
| orchestrator-and-fusion-010 | 2, 3, 9 |
| orchestrator-and-fusion-011 | 3, 9 |
| orchestrator-and-fusion-012 | 2, 3, 9 |
| orchestrator-and-fusion-013 | 5, 6, 9 |
| orchestrator-and-fusion-014 | 3, 5, 9 |
| orchestrator-and-fusion-015 | 1, 2, 9 |
| orchestrator-and-fusion-016 | 1, 2, 9 |
| orchestrator-and-fusion-017 | 2, 9 |

Every requirement id (`orchestrator-and-fusion-001..017`) appears in at least one task. Verification =
pytest (task 9) + the eval fusion Cases (tasks 7, 8, 10) + CI.
