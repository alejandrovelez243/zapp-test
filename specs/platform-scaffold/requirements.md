# Platform Scaffold Requirements

## Summary

The foundational, reproducible monorepo skeleton that every feature spec builds on. It establishes
the `backend/` (uv) and `frontend/` (pnpm) projects, the canonical `TurnOutput` contract model and
config seam, a one-command Docker Compose local runtime (with a pgvector database), the Alembic
baseline, and a minimal CI pipeline — plus a **stub** `POST /chat` that returns a valid placeholder
`TurnOutput` so the contract seam is provable before any feature logic exists. This feature contains
no real agent, language, RAG, or guardrail logic.

## Persona & job-to-be-done

As a developer/operator, I need the whole stack to boot locally with one command, expose a stable
per-turn contract seam, and be CI-verified, so that feature specs (`multilingual`, `guardrails`, …)
can be implemented on a green, reproducible base.

## In / Out of scope

In scope: monorepo layout; uv backend project (`uv init` + base deps via `uv add`); `backend/app/`
package (single config module with model ids + `supported`/`fallback_lang`, `AgentDeps`, the
`TurnOutput`/`GuardrailReport` models); FastAPI app with `GET /health` and a **stub** `POST /chat`;
safe observability init (Logfire/PostHog no-op without tokens); Alembic init + baseline migration
(`CREATE EXTENSION IF NOT EXISTS vector`); `docker-compose.yml` (db + backend + frontend) and
Dockerfiles; ruff/mypy/pre-commit; `.env.example`; a minimal Next.js App Router + pnpm chat page that
calls `/chat`; minimal GitHub Actions CI (ruff + mypy + pytest + backend image build).

Out of scope (their own specs): real language detection/fusion (`multilingual`); guardrail logic
(`guardrails`); RAG tables/retrieval (`faq-rag`); events/`.ics` (`events`); the eval suite content and
runtime judge (`evaluation`); Railway/Vercel deploy + the eval CI gate (`platform-deploy`); auth
*endpoints* (only the `ADMIN_TOKEN` env var is reserved, no management routes); any real LLM call (the
`/chat` stub must not call a model).

## Config flags & config values

- No new Tier-3 feature flags. The scaffold creates the single config module that later features read
  (`supported = ("es","en","pt")`, `fallback_lang = "en"`, model ids). Observability initializes in a
  safe degraded/no-op mode when `LOGFIRE_TOKEN` / `POSTHOG_KEY` are absent (a safe default, not a flag).

## User Stories

- As a developer, I want one command (`docker compose up --build`) to boot the whole stack, so that I
  can run and test features without manual setup.
- As a developer, I want the `TurnOutput` model and a stub `/chat` seam to already exist, so that
  feature work plugs into a stable interface.
- As an operator, I want migrations to run automatically and pgvector to be available, so that the DB
  is ready for feature tables.
- As a maintainer, I want CI to lint, type-check, test, and build on every push, so that the scaffold
  stays green.

## Acceptance Criteria

1. THE SYSTEM SHALL provide a monorepo with a `backend/` uv project and a `frontend/` pnpm project at the repository root.   <!-- eval: platform-scaffold-001 -->
2. THE SYSTEM SHALL manage backend dependencies in `backend/pyproject.toml` via uv with a committed `uv.lock`.   <!-- eval: platform-scaffold-002 -->
3. THE SYSTEM SHALL manage frontend dependencies in `frontend/package.json` via pnpm with a committed `pnpm-lock.yaml`.   <!-- eval: platform-scaffold-003 -->
4. WHEN a developer runs `docker compose up --build` THE SYSTEM SHALL start the database, backend, and frontend services.   <!-- eval: platform-scaffold-004 -->
5. WHEN the database service starts THE SYSTEM SHALL use a Postgres image that provides the `vector` extension (pgvector).   <!-- eval: platform-scaffold-005 -->
6. WHEN the backend container starts THE SYSTEM SHALL run `alembic upgrade head` before serving requests.   <!-- eval: platform-scaffold-006 -->
7. THE SYSTEM SHALL include an Alembic baseline migration that runs `CREATE EXTENSION IF NOT EXISTS vector`.   <!-- eval: platform-scaffold-007 -->
8. WHEN a client requests `GET /health` THE SYSTEM SHALL respond with HTTP 200 and a JSON status body.   <!-- eval: platform-scaffold-008 -->
9. WHEN a client sends `POST /chat` with a message THE SYSTEM SHALL respond with a valid `TurnOutput` JSON object containing all nine contract fields.   <!-- eval: platform-scaffold-009 -->
10. WHILE no feature logic is implemented THE SYSTEM SHALL have the `POST /chat` stub return `needs_review=true` and a fixed placeholder `reply` without calling an LLM.   <!-- eval: platform-scaffold-010 -->
11. THE SYSTEM SHALL define the canonical `TurnOutput` and `GuardrailReport` Pydantic models exactly per the constitution's per-turn JSON contract.   <!-- eval: platform-scaffold-011 -->
12. THE SYSTEM SHALL define `AgentDeps` and a single config module holding the model ids and the `supported=("es","en","pt")` / `fallback_lang="en"` settings.   <!-- eval: platform-scaffold-012 -->
13. IF `LOGFIRE_TOKEN` or `POSTHOG_KEY` is absent THEN THE SYSTEM SHALL start the backend without error, initializing observability in a safe no-op mode.   <!-- eval: platform-scaffold-013 -->
14. THE SYSTEM SHALL configure ruff (lint + format) and mypy in `backend/pyproject.toml` and a `.pre-commit-config.yaml` running ruff, ruff-format, and mypy.   <!-- eval: platform-scaffold-014 -->
15. WHEN `uv run ruff check .` and `uv run mypy` run on the scaffold THE SYSTEM SHALL report no errors.   <!-- eval: platform-scaffold-015 -->
16. WHEN CI runs on push or pull request THE SYSTEM SHALL execute ruff, mypy, pytest, and a backend Docker image build, failing the pipeline on any error.   <!-- eval: platform-scaffold-016 -->
17. THE SYSTEM SHALL provide a `.env.example` listing required env vars (`ANTHROPIC_API_KEY`, `DATABASE_URL`, `ADMIN_TOKEN`, `LOGFIRE_TOKEN`, `POSTHOG_KEY`, `IPINFO_TOKEN`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_POSTHOG_KEY`) with safe placeholder values.   <!-- eval: platform-scaffold-017 -->
18. WHEN the frontend chat page loads and submits a message THE SYSTEM SHALL POST to `/chat` via `NEXT_PUBLIC_API_URL` and display the returned `reply`.   <!-- eval: platform-scaffold-018 -->
19. WHEN `uv sync --frozen` and `pnpm install --frozen-lockfile` run THE SYSTEM SHALL succeed, proving manifests and lockfiles are in sync (deps were added via `uv add` / `pnpm add`, not hand-edited).   <!-- eval: platform-scaffold-019 -->

## Case-id map

`platform-scaffold-001..019` map 1:1 to **smoke / CI checks** (pytest tests, a boot smoke test, and CI
steps), NOT to `pydantic-evals` LLM-judge Cases — this feature is infrastructure, not conversational
behavior. The `evaluation` feature owns the LLM-judge dataset; these ids are asserted by
`uv run pytest` and the CI pipeline. Ids are append-only and never renumbered.

## Non-functional / contract

- **Owns** the canonical `TurnOutput` + `GuardrailReport` models and the config module (the integration
  seam), but **does not compute** any contract field values: the `/chat` stub emits type-valid
  placeholders for all nine fields (`detected_lang="en"`, `active_lang="en"`, `lang_confidence=0.0`,
  `final_normalized_text=""`, `detected_country=None`, `confidence_score=0.0`, `needs_review=true`,
  empty `guardrails`) and a fixed `reply`. Real values are filled by `multilingual` and
  `orchestrator-and-fusion`.
- Establishes the ES/EN/PT + `fallback_lang=en` config consumed by later features; no language logic
  runs here.
- Reproducibility: one-command boot (`docker compose up --build`), frozen installs, automatic
  migrations, and pgvector availability are the load-bearing guarantees for every downstream feature.
