# Guardrails Tasks

Ordered, dependency-aware plan for `guardrails` (deterministic core + optional LLM layer, applied at
the `/chat` boundary). Each task = one specialist delegation + one commit. Traceability:
`— _req: <ids> — owner: <specialist>_`. Prereqs (config, detectors, refusal, engine) precede the
wiring. Drive task-by-task via `/implement guardrails`.

> Names MUST match the evaluation adversarial `must_trip` labels (`prompt_injection`, `jailbreak`,
> `pii_detector`, `toxicity`, `secret_leak`, `off_topic`). Un-deferring the eval guardrail thresholds
> is part of this feature; after that the suite + CI gate enforce guardrail precision/recall.

## Tasks

- [x] 1. Add `guardrails_enabled: bool = True` and `guardrails_llm_enabled: bool = False` to `app/config.py` `Settings`. — _req: guardrails-015, guardrails-016 — owner: backend-engineer_

- [x] 2. Implement `app/guardrails/detectors.py` — deterministic, multilingual (ES/EN/PT) detectors: `detect_pii` (email/phone/national-id/card regex) + `redact_pii`; `detect_prompt_injection`; `detect_jailbreak`; `detect_toxicity(text, lang)`; `detect_off_topic` (soft heuristic); `detect_secret_leak` (ADMIN_TOKEN value, `sk-`/`pylf_` key shapes, system-prompt fragments). Pure functions, never raise (engine handles fail-safe). — _req: guardrails-003, guardrails-004, guardrails-005, guardrails-006, guardrails-007, guardrails-008, guardrails-009, guardrails-010, guardrails-011, guardrails-014 — owner: backend-engineer_

- [x] 3. Implement `app/guardrails/refusal.py` — `safe_refusal(active_lang, category)` returning a neutral ES/EN/PT refusal/clarification in `active_lang` that never echoes the offending content. — _req: guardrails-011, guardrails-012 — owner: backend-engineer_

- [ ] 4. Implement `app/guardrails/engine.py` — `GuardrailResult` model + `run_input_guardrails(message, active_lang, settings)` (per-category policy: injection/jailbreak/toxicity → block; pii → redact; off_topic → flag; gated by `guardrails_enabled`) + `run_output_guardrails(reply, settings)` (pii_leak → redact; toxicity/secret_leak → block); fail-safe (security-critical detector error → block + needs_review). — _req: guardrails-003..guardrails-010, guardrails-016, guardrails-019 — owner: backend-engineer_

- [ ] 5. Wire `app/api/chat.py`: run input guardrails BEFORE the agent (block → short-circuit to a safe-refusal `TurnOutput` with `guardrails.input` + `needs_review`, no model call; redact → feed redacted text; flag → carry names), run output guardrails AFTER (block/redact the reply), set `turn.guardrails` + OR `needs_review`, emit Logfire span + PostHog event with NAMES ONLY (no content). — _req: guardrails-001, guardrails-002, guardrails-003..guardrails-010, guardrails-012, guardrails-013 — owner: backend-engineer_

- [ ] 6. Un-defer the eval thresholds: remove `guardrail_precision` + `guardrail_recall` from `DEFERRED_THRESHOLDS` in `backend/evals/config.py` (and update `run.py`/comments) so the suite + CI gate enforce them. — _req: guardrails-018 — owner: eval-engineer_

- [ ] 7. Align + expand `backend/evals/datasets/adversarial.yaml`: ensure every `must_trip` label equals a guardrail name (`prompt_injection`/`jailbreak`/`pii_detector`/`toxicity`/`secret_leak`); add cases per category + benign precision controls so guardrail precision/recall is meaningful. — _req: guardrails-017 — owner: eval-engineer_

- [ ] 8. (Tier-3 flag) Implement the optional LLM guardrail layer behind `guardrails_llm_enabled` — a lazy classifier (or `pydantic-ai-guardrails` `GuardedAgent`, API confirmed at integration) that augments (never replaces) the deterministic verdict; default off. — _req: guardrails-015 — owner: backend-engineer_

- [ ] 9. Add tests: `detectors` (each category incl. ES/EN/PT positives + benign negatives, PII redaction, secret detection), `engine` (block/redact/flag actions + fail-safe on detector error + `guardrails_enabled=false` skip), and the `/chat` boundary (injection→block+refusal+no model call; PII→redact+continue; output secret_leak→block; clean→empty guardrails; names match labels) via TestModel + aiosqlite. — _req: guardrails-001..guardrails-016, guardrails-019 — owner: backend-engineer_

- [ ] 10. Eval verification: run the eval suite so guardrail precision/recall now compute and meet the (un-deferred) thresholds; tune thresholds/datasets if the deterministic core under/over-fires. (The real run needs `PYDANTIC_AI_GATEWAY_API_KEY`; the GuardrailHit logic is unit-verifiable without it.) — _req: guardrails-018 — owner: eval-engineer_

## Coverage

| Req | Tasks |
|---|---|
| guardrails-001 | 5, 9 |
| guardrails-002 | 5, 9 |
| guardrails-003 | 2, 4, 5, 9 |
| guardrails-004 | 2, 4, 5, 9 |
| guardrails-005 | 2, 4, 5, 9 |
| guardrails-006 | 2, 4, 5, 9 |
| guardrails-007 | 2, 4, 5, 9 |
| guardrails-008 | 2, 4, 5, 9 |
| guardrails-009 | 2, 4, 5, 9 |
| guardrails-010 | 2, 4, 5, 9 |
| guardrails-011 | 2, 3, 9 |
| guardrails-012 | 3, 5, 9 |
| guardrails-013 | 5, 9 |
| guardrails-014 | 2, 9 |
| guardrails-015 | 1, 8 |
| guardrails-016 | 1, 4, 9 |
| guardrails-017 | 7 |
| guardrails-018 | 6, 10 |
| guardrails-019 | 4, 9 |

Every requirement id (`guardrails-001..019`) appears in at least one task. Verification = pytest
(task 9) + the eval suite's guardrail precision/recall (tasks 6, 7, 10) + CI.
