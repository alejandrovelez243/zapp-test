# Events Tasks

Ordered, dependency-aware plan for `events` (admin-managed events + name-only enrollment → localized
`.ics`; events sub-agent as orchestrator tool with confirm-before-enroll + own memory; admin frontend).
Each task = one specialist delegation + one commit. Traceability: `— _req: <ids> — owner: <specialist>_`.
Prereqs (dep, config, models/migration) precede consumers. Drive via `/implement events`.

> `.ics` via the `ics` library; times localized to the detected timezone (geo-fusion), summary/description
> in `active_lang`. Enroll is confirm-before-write; the agent passes a resolved `event_id` (never invents).
> Persisted: `session_id + event_id + name + timestamp` only (NO email). Flag `events_enabled` (default on).

## Tasks

- [x] 1. Add the `.ics` dependency via `uv add ics` (do NOT hand-edit `pyproject.toml`/`uv.lock`). — _req: events-012 — owner: devops-engineer_

- [x] 2. Add `events_enabled: bool = True` to `app/config.py` `Settings`. — _req: events-018 — owner: backend-engineer_

- [x] 3. Implement `app/events/models.py` — `Event` (id/title/description/start_at/end_at/location/timezone/created_at) + `Enrollment` (id/session_id idx/event_id FK idx/name/created_at, no email); Alembic migration `0007` creating both tables (naive-UTC; `now_utc` from `app/time.py`); delete-event cascades enrollments. — _req: events-001, events-004, events-010, events-017 — owner: backend-engineer_

- [x] 4. Implement `app/events/ics.py` — `build_ics(*, summary, description, start_at, end_at, location, tz) -> str` via the `ics` library: RFC-5545 VCALENDAR, times localized to `tz`; summary/description passed in already-`active_lang`. — _req: events-011, events-012 — owner: backend-engineer_

- [x] 5. Implement `app/agents/events.py` — lazy `get_events_agent()` (worker model, `output_type=str`, instructions: help with events; to enroll ask name + which event, CONFIRM event+name before enrolling, call enroll only after the user agrees, never invent an event, reply in `active_lang`) + `@events_agent.tool list_events` (read Event rows id/title/start/end) + `@events_agent.tool enroll(event_id, name)` (verify event exists else message+no write; persist `Enrollment(session_id, event_id, name)`; build `.ics` text in `ctx.deps.active_lang`, tz from `ctx.deps.geo.timezone`; return confirmation + `/events/{id}/ics`). — _req: events-007, events-008, events-009, events-010, events-013, events-015 — owner: backend-engineer_

- [x] 6. Wire the orchestrator (`app/agents/orchestrator.py`): `@orchestrator.tool ask_events(request)` forwarding `deps`+`usage` (honoring `UsageLimits`), gated by `events_enabled` (tool not registered when off); events sub-agent keeps its OWN per-session history (`events_history_json` column on `ConversationSession` + `SessionRepository.load/save_events_messages`, migration `0008`); instruction nudge to route event questions to `ask_events`; enroll/`.ics` errors degrade to a valid contract with `needs_review=true`. — _req: events-014, events-015, events-016, events-018 — owner: backend-engineer_

- [x] 7. Implement `app/api/events.py` — `POST /events` (admin) create; `GET /events` (admin) list id/title/start/end; `DELETE /events/{id}` (admin) delete + cascade; `GET /events/{id}/enrollments` (admin) names + timestamps; `GET /events/{id}/ics` (anonymous) the event `.ics`; missing/invalid admin token on gated routes → 401/403 + no mutation/disclosure. Register the router in `app/main.py`. — _req: events-001, events-002, events-003, events-004, events-005, events-010 — owner: backend-engineer_

- [x] 8. Add the admin frontend events section (extend `frontend/app/admin`, reuse the documents-UI pattern + `X-Admin-Token`): create-event form, event list with delete, and a per-event registrants view (`GET /events/{id}/enrollments`). — _req: events-006 — owner: frontend-engineer_

- [x] 9. Add tests: models + migration 0007/0008 (offline SQL, cascade); `build_ics` (valid RFC-5545, tz localization, active_lang text); events agent (TestModel + mocked DB: list_events, confirm-then-enroll persists, non-existent event → no write, reply in active_lang); `ask_events` forwards deps/usage + `events_enabled` off → tool absent + degrade on error; endpoints (admin auth reject, create/list/delete, enrollments view, `.ics` download); sub-agent memory two-turn. — _req: events-001..events-018 — owner: backend-engineer_

- [x] 10. Add eval Cases + verification: `events` Cases in `backend/evals/datasets/` — coverage is split between offline eval (chat-observable without DB) and pytest (DB/endpoint-dependent).  Eval Cases added: `events-007` (happy/ES — list-events conversational), `events-008` (happy/EN — enroll-intent conversational), `events-009` (happy/PT — confirm-before-enroll conversational), `events-015` (multilingual/FR — unsupported-language fallback + needs_review=true).  In the no-DB offline harness, `ask_events` catches the DB failure and returns a safe string; the orchestrator replies in `active_lang` with `needs_review=false`, making the conversational behavior chat-observable.  DB-dependent paths (`events-001..006`, `events-010..014`, `events-016..018`) are fully covered by the 56 pytest unit tests in task 9.  (Real gateway run needs `PYDANTIC_AI_GATEWAY_API_KEY`.) — _req: events-007, events-008, events-009, events-015 (eval); events-001..006, events-010..014, events-016..018 (pytest task 9) — owner: eval-engineer_

## Coverage

| Req | Tasks | Verification method |
|---|---|---|
| events-001 | 3, 7, 9, 10 | pytest (task 9) — admin CRUD via HTTP, needs DB |
| events-002 | 7, 9, 10 | pytest (task 9) — 401/403 auth reject, needs DB |
| events-003 | 7, 9, 10 | pytest (task 9) — GET /events list, needs DB |
| events-004 | 3, 7, 9, 10 | pytest (task 9) — DELETE + cascade, needs DB |
| events-005 | 7, 9, 10 | pytest (task 9) — GET registrants, needs DB |
| events-006 | 8, 10 | frontend/integration check — admin UI, needs browser |
| events-007 | 5, 9, 10 | **eval Case events-007** (chat-observable, no DB) + pytest (task 9) |
| events-008 | 5, 9, 10 | **eval Case events-008** (chat-observable, no DB) + pytest (task 9) |
| events-009 | 5, 9, 10 | **eval Case events-009** (chat-observable, no DB) + pytest (task 9) |
| events-010 | 3, 5, 7, 9, 10 | pytest (task 9) — Enrollment persist + .ics return, needs DB |
| events-011 | 4, 9, 10 | pytest (task 9) — .ics tz localisation, needs DB |
| events-012 | 1, 4, 9, 10 | pytest (task 9) — RFC-5545 validation, unit-testable |
| events-013 | 5, 9, 10 | pytest (task 9) — non-existent event guard, needs DB |
| events-014 | 6, 9, 10 | pytest (task 9) — deps+usage forwarding, TestModel |
| events-015 | 5, 6, 9, 10 | **eval Case events-015** (multilingual fallback, no DB) + pytest (task 9) |
| events-016 | 6, 9, 10 | pytest (task 9) — degrade → needs_review, no DB required |
| events-017 | 3, 9, 10 | pytest (task 9) — name-only schema, unit-testable |
| events-018 | 2, 6, 9, 10 | pytest (task 9) — events_enabled=False gate, TestModel |

Every requirement id (`events-001..018`) appears in ≥1 task.
Verification = pytest (task 9) for DB/endpoint-dependent paths + eval Cases (task 10)
for chat-observable paths (`events-007`, `events-008`, `events-009`, `events-015`) + CI.

**Eval vs pytest split (task 10 honesty note):**
- **Eval-cased (chat-observable without DB):** `events-007`, `events-008`, `events-009`, `events-015`
  In the no-DB offline harness `ask_events` catches the session=None failure and returns a safe
  fallback string; the orchestrator produces a valid `TurnOutput` in `active_lang` with
  `needs_review=false`.  This makes conversational engagement (orchestrator routes to events tool,
  replies in correct language) observable.  The actual list/enroll/ICS logic is pytest-covered.
- **Pytest-only (DB/endpoint-dependent):** `events-001..006`, `events-010..014`, `events-016..018`
  These require a real Postgres session, admin-token enforcement, or actual `.ics` generation and
  are fully covered by the 56 pytest unit tests in task 9 (TestModel + mocked DB).
