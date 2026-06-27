# Guardrails Tasks (framework migration)

Migrate guardrails from the hand-rolled deterministic core to `pydantic-ai-guardrails` `GuardedAgent`.
Each task = one specialist delegation + one commit. `— _req: <ids> — owner: <specialist>_`.

> The package (`pydantic-ai-guardrails` 0.2.2) is already installed. Goal: drop ~1,200 lines
> (detectors/engine/llm), keep `refusal.py` + a thin adapter, wrap the orchestrator in `GuardedAgent`.

## Tasks

- [x] 1. Wrap the orchestrator in `GuardedAgent` (`app/agents/orchestrator.py`): lazy `get_guarded_orchestrator()` with `input_guardrails=[pii_detector(), prompt_injection(), toxicity_detector(), secret_redaction()]`, `output_guardrails=[toxicity_detector(), secret_redaction(), pii_detector()]`, `on_block="raise"`. Probe the installed package's exact guard names/signatures first. — _req: guardrails-001, guardrails-003, guardrails-004, guardrails-005, guardrails-006, guardrails-008, guardrails-009, guardrails-010, guardrails-014 — owner: backend-engineer_

- [x] 2. Add `app/guardrails/adapter.py`: map the package's fired-guardrail names → the contract vocabulary (`guardrails.input/output`) aligned with the eval `must_trip` labels; `category_for(names)` → refusal category; fail-safe (guard/tripwire error → treat as block). — _req: guardrails-002, guardrails-017, guardrails-019 — owner: backend-engineer_

- [x] 3. Simplify `app/api/chat.py`: replace the `GuardrailEngine.run_input/run_output` calls with a single guarded-agent run inside `try/except <tripwire>`; on tripwire → safe-refusal `TurnOutput` (no model call) + populate `guardrails` + `needs_review`; framework applies pii/secret redaction. `guardrails_enabled=false` → run the plain orchestrator. — _req: guardrails-001, guardrails-012, guardrails-013, guardrails-016 — owner: backend-engineer_

- [x] 4. Delete `app/guardrails/{detectors.py,engine.py,llm.py}`; keep `app/guardrails/refusal.py` (ES/EN/PT) + `__init__.py` exports updated. — _req: guardrails-011 — owner: backend-engineer_

- [x] 5. Wire `guardrails_llm_enabled` → add the package's `llm_judge` guard when set (config unchanged). — _req: guardrails-015 — owner: backend-engineer_

- [ ] 6. Align `backend/evals/datasets/adversarial.yaml` `must_trip` labels to the package's guardrail names. — _req: guardrails-017 — owner: eval-engineer_

- [x] 7. Tests: delete the detector/engine unit tests; add `GuardedAgent` wiring test, `adapter` mapping/fail-safe test, and `/chat` boundary tests (injection→block+refusal+no model call via TestModel; pii/secret redaction; clean→empty). — _req: guardrails-001..guardrails-016, guardrails-019 — owner: backend-engineer_

- [ ] 8. Eval verification: real run — guardrail precision/recall still meet thresholds with the framework guards; tune dataset/labels if needed. — _req: guardrails-018 — owner: eval-engineer_

## Coverage

| Req | Tasks |
|---|---|
| guardrails-001 | 1, 3, 7 |
| guardrails-002 | 2, 7 |
| guardrails-003..006, 008..010 | 1, 7 |
| guardrails-007 | 1 |
| guardrails-011 | 4, 7 |
| guardrails-012 | 3, 7 |
| guardrails-013 | 3, 7 |
| guardrails-014 | 1 |
| guardrails-015 | 5, 7 |
| guardrails-016 | 3, 7 |
| guardrails-017 | 2, 6 |
| guardrails-018 | 8 |
| guardrails-019 | 2, 7 |

Every `guardrails-001..019` appears in ≥1 task. Verification = pytest (7) + eval guardrail metrics (6, 8).
