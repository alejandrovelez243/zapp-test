# Project Constitution — Zapp Global Philosophy School Agent

> **Status:** Canonical. This is the FIRST committed SDD artifact. Every `specs/<feature>/`
> (requirements.md, design.md, tasks.md) and every line of code MUST obey it. Conflicts are
> resolved in favor of this document. Amendments require a dedicated commit that edits this file
> BEFORE any dependent spec or code changes.

## 1. Purpose

We are building a multilingual conversational agent for a Philosophy School platform. The runtime
is a PydanticAI **orchestrator** that routes (agent-as-tool) to (a) a **FAQ-RAG** agent over
uploaded documents and (b) an **EVENTS** agent that enrolls a user and returns a `.ics` file. An
**end-of-conversation evaluation** runs on goodbye/timeout. Documents and events are managed
(upload/delete/list) via the platform.

This constitution fixes the contracts that cut across every feature: the per-turn output shape,
the language policy, the guardrail taxonomy, the resilience posture, the evaluation thresholds, the
tech stack, and the Spec-Driven Development (SDD) workflow. It exists so that independently authored
specs stay mutually consistent and so that the grader can trace one rule from constitution → spec →
EARS acceptance criterion → eval Case → passing CI.

## 2. The Per-Turn JSON Contract

Every conversational turn — from every agent path — MUST emit exactly this structure as its
`output_type`. It is non-negotiable and reproduced here verbatim:

```json
{
  "reply": "string",                  // user-facing answer
  "detected_lang": "es",              // ISO 639-1 the user wrote in
  "active_lang": "es",                // language the session is locked to
  "lang_confidence": 0.97,            // agreement score LLM vs detector
  "final_normalized_text": "string",  // LLM + API fused, locale-normalized
  "detected_country": "MX",           // fused geo signal (ISO 3166-1 alpha-2)
  "confidence_score": 0.0,            // combined logic
  "needs_review": false,              // true on low confidence / divergence / errors
  "guardrails": { "input": [], "output": [] }  // triggered guardrail names
}
```

### 2.1 Field semantics

| Field | Type | Source | Meaning |
|---|---|---|---|
| `reply` | string | production LLM | User-facing answer; MUST be written in `active_lang`. |
| `detected_lang` | ISO 639-1 | LLM | Language the user wrote this turn in. |
| `active_lang` | ISO 639-1 | session state | Language the session is locked to (first supported language seen, else fallback). |
| `lang_confidence` | float 0–1 | fusion | Agreement score between the LLM's `detected_lang` and the deterministic `lingua` detector. |
| `final_normalized_text` | string | LLM + API fused | Cleaned/normalized user text reconciled with the resolved locale (e.g. relative dates resolved to the user's timezone). |
| `detected_country` | ISO 3166-1 alpha-2 | geo-IP fusion | Country fused from the geo-IP API on the request IP; also localizes `.ics` event times. |
| `confidence_score` | float 0–1 | combined logic | Overall trust in this turn (language agreement, retrieval quality, guardrail clean, signal agreement). |
| `needs_review` | bool | reconciliation | `true` on low confidence, signal divergence, unsupported language, or any caught error. |
| `guardrails.input` | string[] | input guardrails | Names of triggered inbound guardrails (empty when clean). |
| `guardrails.output` | string[] | output guardrails | Names of triggered outbound guardrails (empty when clean). |

### 2.2 Reconciliation rules (deterministic)

Fusion happens INSIDE a PydanticAI tool (a traceable Logfire span); reconciliation happens in an
`@agent.output_validator`. Signals fused: geo-IP API (`ipinfo.io` / `ipapi.co`) → `detected_country`;
the `lingua` detector vs the LLM `detected_lang` → `lang_confidence`; REST Countries API enriches
timezone/locale (pt-BR vs pt-PT, es-ES vs es-MX).

1. **Agreement** (LLM detected_lang == detector; geo signal coherent) → high `confidence_score`,
   `needs_review=false`.
2. **Disagreement** (LLM detected_lang ≠ detector, or geo/locale divergence) → lower
   `confidence_score`, `needs_review=true`.
3. **Errors** (geo-IP/REST-Countries call fails, RAG empty/low-confidence, model error caught at the
   FastAPI boundary) → `needs_review=true` and degrade gracefully; never crash the turn.

The output validator MUST also enforce `reply` language == `active_lang` (raise
`ModelRetry('reply must be written in <active_lang>')` on mismatch). Output validators also run on
streaming partials — guard cross-field checks with `if ctx.partial_output: return output`.

## 3. Supported Languages

**Supported languages: ES, EN, PT.** The session locks `active_lang` to the first supported language
detected and stays locked unless the user explicitly switches to another supported language.

- **Configured fallback:** `EN` (single source of truth in the config module; do not hardcode
  elsewhere).
- **Graceful-degradation policy for unsupported input:** `Unsupported language -> set active_lang to
  the configured fallback AND needs_review=true, degrade gracefully.` The agent answers in the
  fallback language, states (in that language) that it currently supports ES/EN/PT, and never errors.
- **Locale resolution:** `detected_country` + REST Countries resolves regional variants (pt-BR vs
  pt-PT, es-ES vs es-MX) for date/number formatting and `.ics` event times. The variant affects
  formatting only; `active_lang` remains the ISO 639-1 base.

## 4. Guardrail Policy

Guardrails are measurable and traceable. The third-party `pydantic-ai-guardrails` (v0.2.x) supplies
ready PII/injection/toxicity/secret-redaction detectors via
`GuardedAgent(agent, input_guardrails=[...], output_guardrails=[...], on_block=..., max_retries=N,
parallel=True)`; the native PydanticAI Hooks layer (`before_model_request`, `before_tool_execute`,
`on_model_request_error`) handles inbound redaction, gating the destructive enroll action, and
fallback. Every trigger appends its name to `guardrails.input` / `guardrails.output` and emits a
Logfire span (install `[telemetry]`, `configure_telemetry(enabled=True)`).

- **Input taxonomy:** prompt-injection, jailbreak, PII, toxicity, off-topic/out-of-scope.
- **Output taxonomy:** PII leakage, unsupported/hallucinated claim, toxicity, language mismatch.

### 4.1 Four-layer safety taxonomy (coverage checklist, borrowed from ADK)

ADK is a **rejected runtime** (see design.md), but its layered safety model is adopted purely as a
coverage checklist — every guardrail must map to one of these layers:

1. **Identity & authorization** — admin-token gates doc/event management; anonymous chat carries a
   `session_id`; email collected only at enroll time.
2. **Input guardrails** — the input taxonomy above, applied before the model request.
3. **Tool / action gating** — the destructive enroll action passes through a human-in-the-loop
   confirmation (pydantic-graph) and a `before_tool_execute` gate; RAG and geo tools are read-only.
4. **Output guardrails & post-processing** — the output taxonomy above, applied in the output
   validator before the turn returns.

A blocked input MUST still return a valid contract object (`needs_review=true`, guardrail named) — it
never raises to the user.

## 5. Resilience Policy

The system degrades, it does not crash. A turn always returns a valid contract object.

- **Timeouts:** every model and HTTP call is bounded (per-provider model settings, e.g.
  `AnthropicModelSettings(timeout=...)` / `OpenAIModelSettings(timeout=...)`; `httpx` timeouts
  on geo-IP / REST Countries).
- **Fallback model:** `FallbackModel(primary, secondary)` for retryable API errors.
  FallbackModel will NOT rescue a structurally-bad 200 — it is always paired with output validators.
- **Retries cap:** `Agent(retries=2)` and `@agent.tool(retries=2)`; `ModelRetry` for self-correction.
  Orchestration is bounded by `UsageLimits(request_limit=8, tool_calls_limit=10,
  total_tokens_limit=20000)`. Sub-agents are re-run with `deps=ctx.deps` AND `usage=ctx.usage`.
- **Caught errors → needs_review:** at the FastAPI boundary catch `ModelHTTPError`,
  `UnexpectedModelBehavior`, and `UsageLimitExceeded`; degrade to `needs_review=true` with a safe
  fallback `reply`.
- **RAG safety:** low retrieval confidence / empty results → lower `confidence_score` +
  `needs_review=true`; never fabricate an answer.

## 6. Eval Thresholds

Thresholds live in ONE config module (CI uses the cheaper judge model; values are configurable in one
place). `pydantic-evals` has no built-in CI exit code, so we compute thresholds and `sys.exit(1)` on
breach; it does not compute latency percentiles, so we use `statistics.quantiles`; `LLMJudge` returns
0–1, so we map to the 1–5 scale (or use a structured int judge). The judge model is pinned, runs at
temperature 0, and is distinct in provider/tier from the production agent (reduce self-preference
bias). Values below are **placeholder targets** — tune in config, not in prose.

| Metric | Placeholder target | Notes |
|---|---|---|
| Task success rate | ≥ 90% | Each EARS acceptance line maps 1:1 to an eval Case id. |
| Language fidelity (`reply` == `active_lang`) | ≥ 98% | Across ES/EN/PT + unsupported fallback. |
| Guardrail precision | ≥ 0.90 | Per input/output taxonomy category. |
| Guardrail recall | ≥ 0.95 | Recall weighted higher for safety. |
| LLM-judge quality | ≥ 4.0 / 5 | Mapped from 0–1; pinned judge, temp 0. |
| Latency p50 | ≤ 2500 ms | `statistics.quantiles`; fed by Logfire. |
| Latency p95 | ≤ 6000 ms | Per-turn, end of orchestration. |
| Cost per conversation | ≤ $0.05 | `operation.cost` via genai-prices in Logfire. |

CI exits non-zero on any breach. p50/p95 and cost-per-conversation are sourced from Logfire; runtime
eval scores and per-turn contract fields also feed PostHog dashboards.

## 7. Tech Stack

- **Agent runtime:** PydanticAI only (v1.x) + `pydantic-ai-guardrails` v0.2.x. ADK rejected;
  PageIndex deferred (both documented in design.md).
- **Backend:** FastAPI on Railway; `uv` for deps (added via `uv add` only); Alembic migrations
  (`CREATE EXTENSION IF NOT EXISTS vector`).
- **Local runtime & dependency management:** Docker + Docker Compose bring the stack up
  (`docker compose up --build`); the DB service uses the `pgvector/pgvector` image (dev≈prod parity).
  Python deps are added **only** via `uv add`, frontend deps **only** via `pnpm add` — `pyproject.toml`/
  `uv.lock` and `package.json`/`pnpm-lock.yaml` are **never hand-edited**; lockfiles are committed and
  installs are frozen in CI/images.
- **Data / RAG:** Postgres + pgvector (HNSW index), pgvector-only, hybrid-ready; SQLModel `Document` /
  `DocumentChunk`; background ingestion; atomic re-ingest swap.
- **Frontend:** Next.js on Vercel (Root Directory `frontend/`; `/ingest` reverse-proxy for PostHog);
  package manager **pnpm** (deps added via `pnpm add` only).
- **Signal fusion APIs:** geo-IP (`ipinfo.io` / `ipapi.co`), `lingua` detector, REST Countries.
- **Evaluation:** `pydantic-evals` (Dataset, Case, evaluators, reports).
- **Observability:** Logfire (backend + LLM tracing/cost/latency, PII-scrubbed) and PostHog (product
  analytics, session replay, feature flags, metadata-only for student messages). Pick one region
  (US or EU) consistently across both.
- **LLM provider:** any PydanticAI-supported provider, selected by the model-string prefix
  (`anthropic:` / `openai:` / `google-gla:` / `groq:` / `mistral:` / …). Model strings live in
  ONE config module; the API key for whichever provider you use is read from env (e.g.
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`). No single provider is required or
  mandated. Model ids are confirmed at integration.

## 8. SDD Workflow & Specs-Before-Code

The git history MUST show this order, with **specs committed before code**:

1. **specify** → `specs/<feature>/requirements.md` (user stories + EARS acceptance criteria, each
   numbered and mapped 1:1 to an eval Case id).
2. **design** → `specs/<feature>/design.md` (architecture, component contracts, mermaid sequences,
   data models, and an explicit "Open Decisions / Rejected Alternatives" section).
3. **plan-tasks** → `specs/<feature>/tasks.md` (numbered checkbox tasks, each traceable to
   requirement id(s) and the responsible specialist).
4. **implement** → code that satisfies the tasks.
5. **verify** → evals + CI gate.

**Specs-before-code rule (enforced once registered — one manual step, see
`.claude/hooks/README.md`):** the `require-spec` git hook rejects a commit that adds or modifies
code under `backend/` or `frontend/` until at least one committed spec trio (`requirements.md` +
`design.md` + `tasks.md`) exists in HEAD (a repo-level gate, not strict per-feature enforcement).
Code may not land before specs exist. This is graded SDD discipline — do not bypass the hook.

## 9. Definition of Done

A feature is Done only when ALL hold:

- [ ] `requirements.md`, `design.md`, `tasks.md` committed BEFORE the feature's code (hook passes).
- [ ] Every EARS acceptance line maps 1:1 to a passing eval Case id.
- [ ] Every turn emits the §2 contract verbatim; output validator enforces `reply` == `active_lang`.
- [ ] Reconciliation rules (§2.2) implemented: agreement → high `confidence_score`; disagreement /
      errors → `needs_review=true`.
- [ ] ES/EN/PT supported; unsupported → fallback `EN` + `needs_review=true`, degrades gracefully.
- [ ] Guardrails cover the full input/output taxonomy and the 4-layer checklist; triggers named in
      `guardrails` and traced in Logfire.
- [ ] Resilience: timeouts, FallbackModel, retries cap, UsageLimits; caught errors → `needs_review`.
- [ ] Eval thresholds met; CI exits non-zero on breach; thresholds read from the single config module.
- [ ] Signal fusion runs inside a traced PydanticAI tool; reconciliation in an output validator.
- [ ] Logfire + PostHog wired (PII-scrubbed / metadata-only respectively); cost + p50/p95 captured.
- [ ] Code quality: typed deps via `RunContext`, `instructions=` over `system_prompt=`, no globals.
