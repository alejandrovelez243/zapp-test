# backend/ — FastAPI + PydanticAI + SQLModel + pgvector

Path-scoped rules for the backend. Detailed patterns live in the
`pydantic-ai-conventions` and `json-contract` skills — load them when writing agents.
Only write code here when `/implement` is running and a spec trio is already committed.
The `require-spec` hook (active once registered — see `.claude/hooks/README.md`) blocks
`backend/`/`frontend/` commits until at least one committed spec trio exists in `HEAD`.

## Stack

PydanticAI (`pydantic-ai`, v2.x) on any PydanticAI-supported provider, routed through the
**Pydantic AI Gateway** (recommended) or direct provider strings. Gateway model strings use
`gateway/<provider>:<model>` (e.g. `gateway/anthropic:claude-opus-4-6`); direct strings use
`<provider>:<model>` (e.g. `anthropic:claude-opus-4-6`). FastAPI; SQLModel over
Postgres + pgvector (HNSW index); Alembic migrations; `pydantic-ai-guardrails`
(v0.2.x); `pydantic-evals`; Logfire instrumentation. Package manager: `uv`.

- **Add/remove deps ONLY via `uv add <pkg>` / `uv add --dev <pkg>` / `uv remove`.**
  NEVER hand-edit `[project.dependencies]`/`[dependency-groups]` in `pyproject.toml`
  or `uv.lock` — let `uv` write them. Commit `uv.lock`; images/CI use `uv sync --frozen`.
- **Local runtime is Docker Compose** (`docker compose up`): the DB service uses the
  `pgvector/pgvector` image (not plain `postgres`), the backend image installs with
  `uv sync --frozen` and runs `uv run alembic upgrade head` then `uvicorn`.

## PydanticAI conventions (hard rules)

- **`instructions=` over `system_prompt=`.** `system_prompt` persists into downstream
  runs' history and leaks the wrong persona across agents; `instructions` do not. Use
  `@agent.instructions` for dynamic per-run context via `RunContext[AgentDeps]`.
- **Dependency injection only.** A `@dataclass AgentDeps` carried via `RunContext[AgentDeps]`;
  tools via `@agent.tool` / `@agent.tool_plain`. **Never use globals.**
- **Structured output.** `output_type=TurnOutput` (the per-turn JSON contract).
  `@agent.output_validator` enforces cross-field rules (e.g. reply language must equal
  `active_lang`) and may `raise ModelRetry('feedback')`. Output validators also run on
  streaming partials — guard with `if ctx.partial_output: return output`.
- **ALWAYS forward `usage=ctx.usage`** when delegating agent-as-tool:
  `r = await faq_agent.run(q, deps=ctx.deps, usage=ctx.usage)`. Forwarding `deps`
  shares dependencies; forwarding `usage` aggregates token/cost into one `RunUsage`
  and keeps `UsageLimits` correct. Omitting it = per-agent wrong cost + broken limits.
- **Cap usage** on the orchestrator run:
  `UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=20000)`.
- Reserve **pydantic-graph** only for the human-in-the-loop enroll confirmation.

## Resilience -> needs_review

- Wrap the production model in `FallbackModel(primary, secondary)` for retryable API
  errors; set per-provider model settings (e.g. `AnthropicModelSettings(timeout=...)` /
  `OpenAIModelSettings(timeout=...)`); use `Agent(retries=2)` and
  `@agent.tool(retries=2)`; `raise ModelRetry` for self-correction.
- `FallbackModel` will NOT rescue a structurally-bad 200 response — pair it with
  output validators.
- At the **FastAPI boundary**, catch `ModelHTTPError`, `UnexpectedModelBehavior`,
  `UsageLimitExceeded` and **degrade to `needs_review=true`** (never 500 to the user).

## Guardrails (measurable)

Use **`pydantic-ai-guardrails`** for measurable PII / prompt-injection / toxicity /
secret-redaction:
`GuardedAgent(agent, input_guardrails=[pii_detector(), prompt_injection(), ...], output_guardrails=[...], on_block='raise'|'log'|'silent', max_retries=N, parallel=True)`.
Install extras `[telemetry]` + `configure_telemetry(enabled=True)` for Logfire spans;
`[evals]` integrates pydantic-evals. Triggered guardrail names populate
`guardrails.input` / `guardrails.output` in the contract.
Native PydanticAI Hooks (`Hooks().on.before_model_request` for inbound redaction,
`before_tool_execute` to gate the destructive enroll action, `on_model_request_error`
for fallback) are the interception layer — there is **no** `guardrails=[...]` Agent arg.

## RAG (pgvector)

`SQLModel` `Document` + `DocumentChunk` tables; a pgvector `Vector` column with an
HNSW index; top-k cosine retrieval for cross-doc selection. Alembic migration must run
`CREATE EXTENSION IF NOT EXISTS vector`. Document lifecycle: upload -> **background
ingestion job (never inline in the request)** -> list -> delete; update = re-ingest
into new rows, atomic swap, then delete old (treat ingested docs as immutable). Low
retrieval confidence / empty -> lower `confidence_score` + `needs_review=true`.
PageIndex is a documented upgrade path only.

## Code quality

- **OOP + heavy Pydantic** modeling; validate at boundaries, type everything.
- **ruff-clean** (lint + format) before any commit; no unused imports, no bare excepts.
- **Model ids are PLACEHOLDERS that churn** (e.g. `claude-sonnet-4-6`, `claude-opus-4-6`).
  Keep them in **ONE config module** and confirm the exact id at integration time.
  **Default LLM path: Pydantic AI Gateway.** Model strings default to
  `gateway/<provider>:<model>` (e.g. `gateway/anthropic:claude-sonnet-4-6`); the single
  env var `PYDANTIC_AI_GATEWAY_API_KEY` (format `pylf_v1_us_...`, from logfire.pydantic.dev)
  routes to all providers and auto-injects traceparent for Logfire distributed tracing.
  Fallback: use direct `<provider>:<model>` strings and set the matching provider key
  (`ANTHROPIC_API_KEY` for `anthropic:*`, `OPENAI_API_KEY` for `openai:*`, etc.). The LLM
  judge model is pinned (temperature 0, distinct provider/tier from the production agent) in
  that same single config place.

## Observability

`logfire.configure()`; `logfire.instrument_pydantic_ai()`;
`logfire.instrument_fastapi(app)`; `logfire.instrument_httpx(capture_all=True)`
(captures the geo / REST Countries calls you fuse);
`logfire.instrument_sqlalchemy(engine)`. `operation.cost` via genai-prices. Logfire
scrubs PII by default; sample in prod. Send **metadata-only** student-message events
to PostHog (it does not scrub PII).

## Deploy (Railway)

Plain Railway Postgres CANNOT enable pgvector — use the pgvector template/image.
Put `railway.toml` at `backend/railway.toml` (Railway ignores Root Directory for the
config path; reference it explicitly). Pin
`startCommand = 'uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT'` and
`preDeployCommand = 'uv run alembic upgrade head'`.
