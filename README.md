# Zapp Global — Philosophy School Conversational Agent

A production-minded, **multilingual (ES / EN / PT)** conversational agent for an online Philosophy
School, built with **Spec-Driven Development (SDD)**. It answers questions grounded in uploaded
course documents (FAQ-RAG), enrolls students into events, fuses geo/language signals, enforces
input/output guardrails, and emits a **stable per-turn JSON contract**. Ships with a one-command,
CI-ready evaluation suite.

> Built for the *Zapp Global – Conversational AI Agent Assessment*. The repo's git history shows the
> SDD flow **specify → design → plan-tasks → implement → verify**, with specs committed before code.

- **Architecture:** see [`ARCHITECTURE.md`](./ARCHITECTURE.md) — one trace per turn, agent-as-tool
  orchestration, signal fusion, guardrails, eval system.
- **Product vision & scoring map:** [`PROJECT.md`](./PROJECT.md).
- **Engineering principles & the canonical contract:** [`specs/constitution.md`](./specs/constitution.md).

---

## Stack

Next.js (App Router, Vercel) → FastAPI (Railway) → a **PydanticAI** orchestrator that routes
(agent-as-tool) to a **pgvector** FAQ-RAG agent and an events agent. Guardrails are deterministic;
evals use **pydantic-evals**; observability via **Logfire** (backend) — analytics via **PostHog**
(backend only, metadata). LLM access is **Pydantic AI Gateway only** (one key, all providers).

---

## Quick start (Docker Compose)

Local dev runs entirely on Docker Compose — Postgres (`pgvector/pgvector`), the FastAPI backend
(migrate-then-serve), and the Next.js frontend.

```bash
cp .env.example .env        # then fill in PYDANTIC_AI_GATEWAY_API_KEY (see below)
docker compose up --build
```

- Frontend (chat): http://localhost:3000
- Admin console (document corpus): http://localhost:3000/admin — token = `ADMIN_TOKEN` (default `dev-admin`)
- Backend API + docs: http://localhost:8000 · http://localhost:8000/docs

The backend boots **without any LLM key** (migrations + health work); without a gateway key, `/chat`
degrades gracefully to a safe reply with `needs_review=true` (no LLM call). Set the key for real
answers.

> The frontend service live-mounts `./frontend`, so code edits hot-reload — no rebuild needed.

---

## Environment (`.env` at the repo root)

Compose auto-loads a root `.env` and overrides the dev defaults. Only the gateway key is needed for
real LLM behaviour; everything else has a working default.

| Variable | Required? | Default | What it does / where to get it |
|---|---|---|---|
| `PYDANTIC_AI_GATEWAY_API_KEY` | **For real replies & evals** | — | The single key that routes to all providers (OpenAI, Anthropic, …). **Get it from [logfire.pydantic.dev](https://logfire.pydantic.dev) → your project → AI Gateway → create a gateway key.** Format `pylf_v1_us_…` (region is encoded in the prefix). Empty → backend boots, but `/chat` and the eval judge make no LLM call. |
| `PYDANTIC_AI_GATEWAY_BASE_URL` | No | inferred | Override only if you need a non-default gateway endpoint; normally inferred from the key's region prefix. |
| `ADMIN_TOKEN` | No | `dev-admin` | Guards the admin `/documents` endpoints + the `/admin` console. Sent as the `X-Admin-Token` header. |
| `DATABASE_URL` | No | `postgresql+asyncpg://zapp:zapp@db:5432/zapp` | Postgres + pgvector DSN. Keep host `db` for compose. |
| `ORCHESTRATOR_MODEL` | No | `gateway/openai:gpt-4.1` | Orchestrator model string (`gateway/<provider>:<model>`). |
| `WORKER_MODEL` | No | `gateway/openai:gpt-4.1-mini` | FAQ/worker sub-agent model. |
| `JUDGE_MODEL` | No | `gateway/openai:gpt-4.1-mini` | LLM-as-judge model for evals (temperature 0). |
| `LOGFIRE_TOKEN` | No | _(empty → no-op)_ | Logfire backend/LLM tracing + cost/latency. From the same logfire.pydantic.dev project. |
| `POSTHOG_KEY` | No | _(empty → no-op)_ | **Backend-only** product analytics (metadata-only; no frontend SDK). |
| `IPINFO_TOKEN` | No | _(uses ipapi.co free tier)_ | Geo-IP signal for `detected_country` fusion. |

`NEXT_PUBLIC_API_URL` is set by Compose to `http://backend:8000` (the in-network service hostname);
the browser only ever calls same-origin `/api/*` via a Next.js rewrite, so no CORS is needed.

---

## The per-turn JSON contract

Every chat turn emits this stable object (canonical source: `specs/constitution.md`):

```json
{
  "reply": "string",
  "detected_lang": "es",
  "active_lang": "es",
  "lang_confidence": 0.97,
  "final_normalized_text": "string",
  "detected_country": "MX",
  "confidence_score": 0.0,
  "needs_review": false,
  "guardrails": { "input": [], "output": [] }
}
```

`detected_country` is `null` when geo is unavailable (private IP / lookup failure).

---

## Running the tests

**Backend** (pytest — agents, validators, fusion, guardrails, RAG; LLM calls are stubbed):

```bash
cd backend
uv sync
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy                                            # type-check
uv run pytest -q                                       # unit/integration suite
```

CI runs the same against an ephemeral Postgres service.

**Frontend** (Vitest + Testing Library; each test maps 1:1 to a `frontend-shell-*` / `admin-console-*`
acceptance id):

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm typecheck && pnpm lint && pnpm test && pnpm build
```

---

## Running the evals (one command, one report, CI-ready)

The offline suite runs every committed dataset, computes the metrics, writes a report, and **exits
non-zero on any threshold breach**. Requires `PYDANTIC_AI_GATEWAY_API_KEY` (real agent + judge).

```bash
cd backend
uv run python -m evals.run
# → report written to backend/evals/reports/latest-report.md ; exit code 0 (pass) / 1 (breach)
```

CI variant (uses the cheaper CI judge model):

```bash
EVAL_CI=1 uv run python -m evals.run
```

**Reported metrics** (thresholds in `backend/evals/config.py`):

| Metric | Meaning |
|---|---|
| `task_success_rate` | % of cases passing their assertions |
| `language_fidelity` | % of replies in the expected language |
| `guardrail_precision` / `guardrail_recall` | over the adversarial cases |
| `judge_mean` | LLM-as-judge subjective quality, 1–5 rubric, temperature 0 |
| `latency_p50_ms` / `latency_p95_ms` | operational latency |
| `cost_per_conversation_usd` | estimated cost via genai-prices |

A pre-generated example report lives at `backend/evals/reports/example-report.md`.

---

## Adding a new eval case

Cases are committed YAML, version-controlled so every change is reviewable and maps **1:1 to a
numbered acceptance criterion** in `specs/<feature>/requirements.md` (EARS).

1. Pick the dataset under `backend/evals/datasets/`:
   `happy.yaml` · `multilingual.yaml` · `adversarial.yaml` · `fusion.yaml`.
2. Append a case (id should match an acceptance criterion, e.g. `multilingual-006`):

   ```yaml
   - name: happy-es-faq-tuition-cost-01
     inputs:
       message: "¿Cuánto cuesta la matrícula?"
       ip: "189.210.1.1"          # geo-plausible IP for the fusion signal
     expected_output:
       active_lang: es
       needs_review: false
     metadata:
       suite: happy
       lang: es
       must_trip: []              # guardrail names expected to fire (adversarial cases)
   ```

   Special metadata flags the runner honours: `simulate_low_confidence`,
   `simulate_detector_failure`, `assert_all_nine_fields` (see `backend/evals/README.md`).
3. Re-run `uv run python -m evals.run` and confirm the new case passes (and the gate still holds).

---

## Spec-Driven Development

Every feature flows through five gates, each a slash command, **committing the spec before the code**:

```
/specify <feature>    → specs/<feature>/requirements.md   (EARS user stories + numbered criteria)
/design <feature>     → specs/<feature>/design.md          (architecture, contracts, Open Decisions)
/plan-tasks <feature> → specs/<feature>/tasks.md           (traceable checkbox tasks + owner)
/implement <feature>  → backend/ or frontend/ code         (one specialist per task)
/verify <feature>     → evals + tests                      (each acceptance line ↔ a Case/test)
```

A `require-spec` pre-commit hook blocks `backend/`/`frontend/` code until a committed spec trio
exists. Specs delivered: the three reference specs **`multilingual`, `guardrails`, `evaluation`**
plus our own — **`faq-rag`, `orchestrator-and-fusion`, `frontend-shell`, `admin-console`, `events`**.

---

## Trade-offs & known limitations

- **Gateway-only LLM path** (no direct-provider fallback): a `PYDANTIC_AI_GATEWAY_API_KEY` is
  required for real replies and for the eval judge. This centralises cost/tracing but is a hard
  dependency — without it the agent degrades to `needs_review=true`.
- **Eval gate variance:** metrics come from live LLMs, so `task_success`/`judge_mean`/`latency_p95`
  sit close to their thresholds and can flip on run-to-run variance plus the added latency of
  FAQ-RAG retrieval + geo fusion. Treat a single red run as a signal to inspect the per-case report,
  not necessarily a regression.
- **Geo fusion** (`detected_country`) needs a public IP; it is `null` on private/loopback IPs and
  degrades (never blocks) on API failure.
- **Admin console** is an English-only internal tool; it shows a `failed` ingestion status but not
  the underlying reason (the backend `error` field is intentionally not surfaced).
- **Analytics is backend-only** — no PostHog/SDK in the frontend (privacy: no client code that could
  leak message content/PII), so there is no browser session replay.
- **RAG** is pgvector cosine top-k only; hybrid retrieval and PageIndex are documented upgrade paths,
  not built.

## AI assistance

Built with AI copilots (as the assessment expects). Architectural decisions, rejected alternatives,
and where suggestions were accepted vs. overruled are recorded in each `specs/<feature>/design.md`
"Open Decisions / Rejected Alternatives" section and in `PROJECT.md`.
