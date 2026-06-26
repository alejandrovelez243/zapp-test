# Evaluation Tasks

Ordered, dependency-aware plan for `evaluation` (offline pydantic-evals suite + runtime
end-of-conversation judge). Each task = one specialist delegation + one commit. Traceability:
`— _req: <ids> — owner: <specialist>_`. Prereqs (config, judge, models/migrations) precede consumers.
Drive task-by-task via `/implement evaluation`.

> The offline suite runs the REAL orchestrator via the gateway → it costs money and needs
> `PYDANTIC_AI_GATEWAY_API_KEY`. Unit tests mock/TestModel to stay free; only the example-report task
> and CI make real calls. The **guardrail precision/recall threshold is DEFERRED** (disabled in config)
> until the `guardrails` feature populates `guardrails.{input,output}` — keeps CI from going red.

## Tasks

- [x] 1. Create `backend/evals/config.py` — the single source: `JUDGE_MODEL="gateway/openai:gpt-4.1-mini"`, `JUDGE_MODEL_CI`, `JUDGE_TEMPERATURE=0.0`, `THRESHOLDS` (task_success_rate, language_fidelity, guardrail_precision, guardrail_recall, judge_mean, latency_p95_ms, cost_per_conversation_usd) with the **guardrail_* thresholds marked DEFERRED/disabled** until `guardrails` lands, and a `PRICE_TABLE` (USD per 1M in/out tokens per model). — _req: evaluation-007, evaluation-010 — owner: eval-engineer_

- [x] 2. Implement `backend/evals/judge.py` — a structured int judge `Agent(JUDGE_MODEL, output_type=int, model_settings={"temperature":0}, instructions=<documented 1–5 rubric>)` (discrete 1–5, no 0–1 mapping); reusable by offline + runtime. — _req: evaluation-005, evaluation-010 — owner: eval-engineer_

- [x] 3. Implement `backend/evals/task.py` `run_turn(inputs) -> dict` — mirror the `/chat` boundary WITHOUT HTTP/DB (detect → resolve_active_lang → AgentDeps → `get_orchestrator().run` via gateway → reconcile → `TurnOutput.model_dump()`), capturing per-case duration + `RunUsage`. — _req: evaluation-001 — owner: eval-engineer_

- [ ] 4. Implement `backend/evals/evaluators.py` — `TaskSuccess`, `LanguageFidelity` (lingua on reply == active_lang), `GuardrailHit` (compare `guardrails` to `metadata.must_trip` → tp/fp/fn), `SubjectiveQualityJudge` (calls the structured judge). — _req: evaluation-002, evaluation-003, evaluation-004, evaluation-005, evaluation-020 — owner: eval-engineer_

- [x] 5. Author `backend/evals/datasets/happy.yaml` + `backend/evals/datasets/adversarial.yaml` (pydantic-evals `cases`: name/inputs/expected_output/metadata, incl. `must_trip` for adversarial). `multilingual.yaml` already exists. — _req: evaluation-011 — owner: eval-engineer_

- [ ] 6. Implement `backend/evals/run.py` (`python -m evals.run`) + `report.py` — load all datasets, `evaluate_sync(run_turn)`, compute task success %, language fidelity %, guardrail precision/recall, judge mean (1–5), latency p50/p95 (`statistics.quantiles`), cost/conversation (PRICE_TABLE × RunUsage); render ONE markdown report + print summary; compare to `THRESHOLDS` (skip DEFERRED ones) and `sys.exit(1)` on breach; a judge error → case un-judged (not-passing), continue. — _req: evaluation-001, evaluation-006, evaluation-008, evaluation-009, evaluation-019 — owner: eval-engineer_

- [ ] 7. Generate and COMMIT `backend/evals/reports/example-report.md` — a pre-generated example report (run the suite once with `PYDANTIC_AI_GATEWAY_API_KEY`; if no key is available, hand-author a representative report and regenerate later). — _req: evaluation-009, evaluation-013 — owner: eval-engineer_

- [x] 8. Add the `SessionGrade` SQLModel (session_id, score 1–5, rationale, needs_review, model, created_at) + a `graded_at: datetime | None` column on `ConversationSession`, with Alembic migration `0004` (naive-UTC timestamps, matching the project convention). — _req: evaluation-016 — owner: backend-engineer_

- [x] 9. Add `runtime_eval_enabled: bool = True` (flag) and `conversation_idle_timeout: int = 900` to `app/config.py` `Settings`. — _req: evaluation-014, evaluation-018 — owner: backend-engineer_

- [ ] 10. Implement `backend/app/eval/runtime.py` — `async evaluate_conversation(session_id)` (load message_history → judge transcript → persist `SessionGrade` with `needs_review = score < judge_mean` → Logfire span (content) + PostHog event (METADATA-ONLY) → never raises); `is_goodbye(message, lang)` deterministic ES/EN/PT matcher; and the idle-sweep coroutine (idle > timeout AND `graded_at IS NULL` → grade → set `graded_at`). — _req: evaluation-015, evaluation-016, evaluation-017, evaluation-019 — owner: eval-engineer_

- [ ] 11. Wire the runtime triggers: `app/main.py` lifespan starts/stops the idle-sweep task WHERE `runtime_eval_enabled`; `app/api/chat.py` schedules `evaluate_conversation` as a background task after returning the turn when `is_goodbye(...)` and `runtime_eval_enabled`. — _req: evaluation-014, evaluation-015, evaluation-018 — owner: backend-engineer_

- [ ] 12. Add the eval-gate to `.github/workflows/ci.yml` — a step `uv run python -m evals.run` on push/PR with `PYDANTIC_AI_GATEWAY_API_KEY` from GitHub Secrets and the CI judge id; the pipeline fails on non-zero exit. — _req: evaluation-012 — owner: devops-engineer_

- [ ] 13. Add tests: `run.py` threshold/exit logic (mocked metrics → assert `SystemExit`), each evaluator on sample outputs, the structured judge via `TestModel`, `is_goodbye` (ES/EN/PT), `evaluate_conversation` (TestModel + aiosqlite in-memory), and the sweep `graded_at` guard. — _req: evaluation-002, evaluation-003, evaluation-004, evaluation-005, evaluation-008, evaluation-014, evaluation-015, evaluation-016, evaluation-017, evaluation-018, evaluation-019, evaluation-020 — owner: eval-engineer_

## Coverage

| Req | Tasks |
|---|---|
| evaluation-001 | 3, 6 |
| evaluation-002 | 4, 13 |
| evaluation-003 | 4, 13 |
| evaluation-004 | 1 (deferred), 4, 13 |
| evaluation-005 | 2, 4, 13 |
| evaluation-006 | 6 |
| evaluation-007 | 1 |
| evaluation-008 | 6, 13 |
| evaluation-009 | 6, 7 |
| evaluation-010 | 1, 2 |
| evaluation-011 | 5 |
| evaluation-012 | 12 |
| evaluation-013 | 7 |
| evaluation-014 | 9, 10, 11 |
| evaluation-015 | 10, 11, 13 |
| evaluation-016 | 8, 10, 13 |
| evaluation-017 | 10, 13 |
| evaluation-018 | 9, 11, 13 |
| evaluation-019 | 6, 10, 13 |
| evaluation-020 | 4, 13 |

Every requirement id (`evaluation-001..020`) appears in at least one task. Verification = pytest
(task 13) + the offline suite itself (task 6, gated) + CI (task 12).
