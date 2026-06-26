# Platform Scaffold Tasks

Ordered, dependency-aware plan for `platform-scaffold`. Each task = one specialist delegation + one
commit. Traceability: `— _req: <ids> — owner: <specialist>_`. Prerequisites (uv project, config,
models) precede consumers; container/CI tasks come after the code they package. Drive task-by-task via
`/implement platform-scaffold`.

> Verification note: this is an **infrastructure** feature, so its "Cases" are **pytest tests + CI
> steps + a compose smoke check**, not `pydantic-evals` LLM-judge Cases (see the requirements Case-id
> map). The LLM eval suite is owned by `evaluation`.

## Tasks

- [x] 1. Initialize the backend uv project (`uv init`) and add base deps via `uv add` (never hand-edit manifests): `fastapi "uvicorn[standard]" pydantic-ai "pydantic-ai-guardrails[telemetry,evals]" sqlmodel pgvector alembic asyncpg logfire posthog httpx pydantic-settings pydantic-extra-types`; dev group `uv add --dev ruff mypy pytest pytest-asyncio httpx`; commit `uv.lock`. — _req: platform-scaffold-001, platform-scaffold-002, platform-scaffold-019 — owner: devops-engineer_
- [x] 2. Configure ruff (`E,F,W,I,B,UP,ASYNC,SIM,RUF`, line-length 100, py312) + mypy (`strict`, `pydantic.mypy` plugin) in `backend/pyproject.toml`, and `.pre-commit-config.yaml` (ruff, ruff-format, mypy). — _req: platform-scaffold-014, platform-scaffold-015 — owner: devops-engineer_
- [x] 3. Implement `app/config.py` `Settings` (pydantic-settings): `database_url`, `anthropic_api_key`, `admin_token`, optional `logfire_token`/`posthog_key`/`ipinfo_token`, model ids, `supported=("es","en","pt")`, `fallback_lang="en"`. — _req: platform-scaffold-012, platform-scaffold-017 — owner: backend-engineer_
- [ ] 4. Implement `app/contract.py` with the canonical `TurnOutput` + `GuardrailReport` models (verbatim per the json-contract skill; nine fields, constraints). — _req: platform-scaffold-011 — owner: backend-engineer_
- [ ] 5. Implement `app/deps.py` `AgentDeps` dataclass (session, http, session_id, request_ip, active_lang, admin_token). — _req: platform-scaffold-012 — owner: backend-engineer_
- [ ] 6. Implement `app/db.py`: async engine (`asyncpg`) from `settings.database_url`, `async_sessionmaker`, `get_session` dependency. — _req: platform-scaffold-006 — owner: backend-engineer_
- [ ] 7. Implement `app/observability.py` `configure_observability(app)`: wire Logfire (`instrument_fastapi/httpx/sqlalchemy`) only when `logfire_token` set and PostHog only when `posthog_key` set; no-op + no error otherwise. — _req: platform-scaffold-013 — owner: observability-engineer_
- [ ] 8. Implement `app/api/health.py` `GET /health` → 200 `{"status":"ok"}`. — _req: platform-scaffold-008 — owner: backend-engineer_
- [ ] 9. Implement `app/api/chat.py` `POST /chat` STUB: accept `ChatRequest{session_id,message}`, return a type-valid `TurnOutput` placeholder (`needs_review=true`, fixed `reply`, no LLM call). — _req: platform-scaffold-009, platform-scaffold-010 — owner: backend-engineer_
- [ ] 10. Implement `app/main.py`: build FastAPI app, call `configure_observability`, include health + chat routers, set dev CORS. — _req: platform-scaffold-008, platform-scaffold-009 — owner: backend-engineer_
- [ ] 11. Initialize Alembic (`alembic init`) and write the baseline migration `0001_baseline` running `CREATE EXTENSION IF NOT EXISTS vector` (downgrade drops it); `env.py` reads `settings.database_url`. — _req: platform-scaffold-006, platform-scaffold-007 — owner: backend-engineer_
- [ ] 12. Write `backend/Dockerfile` (uv base; `uv sync --frozen --no-dev`; CMD migrate-then-uvicorn), `frontend/Dockerfile` (node + corepack pnpm; `pnpm install --frozen-lockfile`; build), and `.dockerignore`. — _req: platform-scaffold-002, platform-scaffold-003, platform-scaffold-019 — owner: devops-engineer_
- [ ] 13. Write `docker-compose.yml`: `db` (`pgvector/pgvector:pg16` + healthcheck + volume), `backend` (`depends_on` db healthy, `command` = `alembic upgrade head` then uvicorn, port 8000), `frontend` (`NEXT_PUBLIC_API_URL` → backend, port 3000, `pnpm dev`). — _req: platform-scaffold-004, platform-scaffold-005, platform-scaffold-006 — owner: devops-engineer_
- [ ] 14. Write `.env.example` listing `ANTHROPIC_API_KEY`, `DATABASE_URL`, `ADMIN_TOKEN`, `LOGFIRE_TOKEN`, `POSTHOG_KEY`, `IPINFO_TOKEN`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_POSTHOG_KEY` with safe placeholders. — _req: platform-scaffold-017 — owner: devops-engineer_
- [ ] 15. Scaffold the frontend: `pnpm` Next.js App Router project (deps via `pnpm add`/`pnpm dlx create-next-app`), a minimal chat page (`app/page.tsx`) that POSTs to `/chat` via `NEXT_PUBLIC_API_URL` and renders `reply`; commit `pnpm-lock.yaml`. — _req: platform-scaffold-001, platform-scaffold-003, platform-scaffold-018 — owner: frontend-engineer_
- [ ] 16. Add backend tests: `test_health` (200), `test_chat_stub` (valid `TurnOutput`, `needs_review=true`, no LLM), `test_contract` (model shape/constraints), `test_config`/observability no-op-without-tokens. — _req: platform-scaffold-008, platform-scaffold-009, platform-scaffold-010, platform-scaffold-011, platform-scaffold-012, platform-scaffold-013, platform-scaffold-015 — owner: backend-engineer_
- [ ] 17. Write `.github/workflows/ci.yml`: `setup-uv` → `uv sync --frozen` → `ruff check` → `ruff format --check` → `mypy` → `pytest` (with a `pgvector/pgvector:pg16` service container + `alembic upgrade head`) → backend `docker build`; frontend `pnpm install --frozen-lockfile` + `pnpm build`. Fail on any error. — _req: platform-scaffold-015, platform-scaffold-016, platform-scaffold-019 — owner: devops-engineer_
- [ ] 18. Add a compose smoke check (script/CI step): `docker compose up -d` boots db+backend, `GET /health` returns 200, then teardown — proving one-command boot + pgvector + auto-migration. — _req: platform-scaffold-004, platform-scaffold-005, platform-scaffold-006 — owner: devops-engineer_

## Coverage

| Req | Tasks |
|---|---|
| platform-scaffold-001 | 1, 15 |
| platform-scaffold-002 | 1, 12 |
| platform-scaffold-003 | 12, 15 |
| platform-scaffold-004 | 13, 18 |
| platform-scaffold-005 | 13, 18 |
| platform-scaffold-006 | 11, 13, 18 |
| platform-scaffold-007 | 11 |
| platform-scaffold-008 | 8, 10, 16, 18 |
| platform-scaffold-009 | 9, 10, 16 |
| platform-scaffold-010 | 9, 16 |
| platform-scaffold-011 | 4, 16 |
| platform-scaffold-012 | 3, 5, 16 |
| platform-scaffold-013 | 7, 16 |
| platform-scaffold-014 | 2 |
| platform-scaffold-015 | 2, 16, 17 |
| platform-scaffold-016 | 17 |
| platform-scaffold-017 | 3, 14 |
| platform-scaffold-018 | 15, 17 |
| platform-scaffold-019 | 1, 12, 17 |

Every requirement id (`platform-scaffold-001..019`) appears in at least one task. Verification = pytest
(task 16) + CI (task 17) + compose smoke (task 18).
