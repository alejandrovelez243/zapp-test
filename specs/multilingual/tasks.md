# Multilingual Tasks

Ordered, dependency-aware implementation plan for `multilingual`. Each task is one specialist
delegation and one commit. Traceability: `— _req: <ids> — owner: <specialist>_`. Prerequisites
(deps, config, models, migrations) precede consumers. Do not start coding here — drive task-by-task
via `/implement multilingual`.

## Tasks

- [x] 1. Add the deterministic language-detector dependency via `uv add lingua-language-detector` (never hand-edit `pyproject.toml`); refresh `uv.lock`. — _req: multilingual-002 — owner: devops-engineer_

- [x] 2. Add `LanguageConfig` to the single config module: `supported=("es","en","pt")`, `fallback_lang="en"`, `lang_confidence_min=0.55`, `min_input_chars=12`, `autoswitch_min_turns=2`, and the `lang_autoswitch` flag (default `False`). — _req: multilingual-003, multilingual-009, multilingual-011 — owner: backend-engineer_

- [x] 3. Implement `DetectionResult` + `LanguageDetector` (lingua wrapper over a bounded language set): returns top language + confidence, sets `is_reliable=False` for input shorter than `min_input_chars`, and NEVER raises — on any error returns `DetectionResult(lang=None, confidence=0.0, is_reliable=False, error=...)`. — _req: multilingual-002, multilingual-011, multilingual-012 — owner: backend-engineer_

- [x] 4. Implement `compute_lang_confidence(llm_lang, det)` agreement score in `app/lang/fusion.py` (agreement→high, disagreement→low, detector-unreliable→weight LLM, detector-failed→low). — _req: multilingual-005 — owner: backend-engineer_

- [x] 5. Add the `ConversationSession` SQLModel (`active_lang`, `last_supported_lang`, `pending_switch_lang`, `pending_switch_count`) and the Alembic migration creating the table. — _req: multilingual-007 — owner: backend-engineer_

- [x] 6. Implement `resolve_active_lang(session, det, config)` state machine: first-turn lock to supported language; unsupported first turn → `fallback_lang` + `fallback_used`; locked session → keep `active_lang`; unsupported on locked session → keep + needs_review reason; short input → no switch. — _req: multilingual-003, multilingual-004, multilingual-008, multilingual-009, multilingual-011, multilingual-014 — owner: backend-engineer_

- [x] 7. Implement session persistence helpers (load/update `ConversationSession`; `load_messages`/`save_messages` over `result.all_messages()` keyed by `session_id`). — _req: multilingual-007 — owner: backend-engineer_

- [x] 8. Build the orchestrator agent with `output_type=TurnOutput`, dynamic `@instructions` injecting `active_lang`, and the `@output_validator` (guard `partial_output`): set `lang_confidence` via `compute_lang_confidence`; enforce reply language == `active_lang` with `ModelRetry`; set `needs_review` on fallback/detector-failure/low-confidence; low-confidence → `ModelRetry` to ask the user to confirm their language. — _req: multilingual-001, multilingual-005, multilingual-006, multilingual-007, multilingual-010, multilingual-012 — owner: backend-engineer_

- [x] 9. Wire the `POST /chat` FastAPI boundary: detect → `resolve_active_lang` → build `AgentDeps(active_lang, detection)` → `orchestrator.run(..., UsageLimits)` → persist session + messages → return `TurnOutput`; catch `ModelHTTPError|UnexpectedModelBehavior|UsageLimitExceeded` → `degraded_turn(active_lang)` with `needs_review=true` (never a 500). — _req: multilingual-001, multilingual-004, multilingual-008, multilingual-009 — owner: backend-engineer_

- [x] 10. Instrument observability: Logfire span around the detector call (one trace per turn) and a metadata-only PostHog `turn_completed` event (`active_lang`, `detected_lang`, `lang_confidence`, `needs_review` — no message content). — _req: multilingual-001, multilingual-005 — owner: observability-engineer_

- [x] 11. Implement the flag-gated auto-switch (Tier-3): behind `lang_autoswitch`, count consecutive turns in a new supported language and switch `active_lang` at `autoswitch_min_turns`; default off keeps the hard lock. — _req: multilingual-013, multilingual-014 — owner: backend-engineer_

- [x] 12. Add eval Cases `multilingual-001..014` to the `backend/evals/datasets/multilingual.yaml` dataset (happy ES/EN/PT, coherence/switch, unsupported→fallback, short-input, low-confidence/disagreement, detector-failure) with evaluators for language fidelity and the `needs_review`/`active_lang` assertions, so `/verify` runs them. — _req: multilingual-001..multilingual-014 — owner: eval-engineer_

- [x] 13. Add unit tests for the deterministic units (`LanguageDetector`, `compute_lang_confidence`, `resolve_active_lang` state machine incl. lock/switch/fallback/short-input) and an integration test for the `/chat` boundary degrade path. — _req: multilingual-002..multilingual-014 — owner: backend-engineer_

- [x] 14. (Frontend, deferrable) Mirror `active_lang` and surface `needs_review` subtly in the chat UI when the chat surface exists. — _req: multilingual-001 — owner: frontend-engineer_

## Coverage

| Req | Tasks |
|---|---|
| multilingual-001 | 8, 9, 10, 12, 14 |
| multilingual-002 | 1, 3, 12, 13 |
| multilingual-003 | 2, 6, 12 |
| multilingual-004 | 6, 9, 12 |
| multilingual-005 | 4, 8, 10, 12 |
| multilingual-006 | 8, 12 |
| multilingual-007 | 5, 7, 8, 12 |
| multilingual-008 | 6, 9, 12 |
| multilingual-009 | 2, 6, 9, 12 |
| multilingual-010 | 8, 12 |
| multilingual-011 | 2, 3, 6, 12 |
| multilingual-012 | 3, 8, 12, 13 |
| multilingual-013 | 11, 12 |
| multilingual-014 | 6, 11, 12 |

Every requirement id (`multilingual-001..014`) appears in at least one task. Eval Cases (task 12) cover
all 14 ids 1:1; deterministic logic is unit-tested (task 13).
