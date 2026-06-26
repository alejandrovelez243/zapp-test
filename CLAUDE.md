# Zapp Global — Philosophy School Platform (SDD)

This repository builds an AI agent platform for an online Philosophy School using
**Spec-Driven Development (SDD)**. A conversational agent answers questions over
uploaded course documents (FAQ-RAG) and enrolls students into events (returns an
`.ics` calendar file), with an end-of-conversation evaluation.

All repo artifacts (specs, docs, agents, skills, code) are written in **English**.
The **product** serves end users in **ES / EN / PT** at runtime.

## SDD workflow — specs before code (NON-NEGOTIABLE)

Every feature flows through five phases, in this order. Each phase is driven by a
slash command run in the main session:

1. `/specify <feature>`   -> `specs/<feature>/requirements.md` (EARS user stories + numbered acceptance criteria)
2. `/design <feature>`    -> `specs/<feature>/design.md` (architecture, contracts, mermaid, **Open Decisions / Rejected Alternatives**)
3. `/plan-tasks <feature>`-> `specs/<feature>/tasks.md` (numbered checkbox tasks, each traceable to a requirement id + specialist)
4. `/implement <feature>` -> application code under `backend/` or `frontend/`
5. `/verify <feature>`    -> runs evals/tests; each acceptance line maps 1:1 to an eval Case id

**Rule: specs are COMMITTED BEFORE the code they govern.** A `require-spec` git
hook (pre-commit) — enforced once registered (one manual step — see
`.claude/hooks/README.md`) — blocks commits that add/modify code under `backend/` or
`frontend/` until at least one committed `specs/<feature>/` spec trio exists in HEAD
(a repo-level gate, not strict per-feature enforcement).
Git history must visibly show: specify -> design -> plan-tasks -> implement -> verify.

Do not hand-write specs ad hoc — use the commands so structure and traceability
stay consistent.

## Supported languages

Supported languages: **ES, EN, PT**. Unsupported language -> set `active_lang` to
the configured fallback AND `needs_review=true`, degrade gracefully.

## Per-turn JSON contract (verbatim, non-negotiable; every turn emits this)

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

This contract is canonical. When restating it anywhere, keep it textually identical.

## Tech stack (one-liner)

Next.js (Vercel) -> FastAPI (Railway) -> a **PydanticAI** orchestrator that routes
(agent-as-tool) to a **pgvector** FAQ-RAG agent and an **events** agent (`.ics`);
guardrails via `pydantic-ai-guardrails`; evals via `pydantic-evals`; observability
via **Logfire** (engineering/LLM tracing/cost) + **PostHog** (product analytics).

## Signal fusion (the graded API Integration & Signal Fusion)

Fuse an external geo-IP API on the request IP -> `detected_country`, a deterministic
`lingua` language detector fused with the LLM's `detected_lang` -> `lang_confidence`
(agreement score), enriched via REST Countries for timezone/locale. Fusion happens
**inside a PydanticAI tool** (a traceable Logfire span); reconciliation happens in an
**output_validator**. Agreement -> high `confidence_score`; disagreement ->
`needs_review=true`.

## Dependency & runtime conventions (hard rules)

- **Local dev runs on Docker + Docker Compose.** `docker compose up` brings up Postgres
  (the `pgvector/pgvector` image, so `CREATE EXTENSION vector` works), the FastAPI backend,
  and (optionally) the frontend. Do not assume a host Postgres or a host Python/Node env.
- **Python deps are added ONLY via `uv add <pkg>` / `uv add --dev <pkg>`** (removed via
  `uv remove`). **NEVER hand-edit** `[project.dependencies]` / `[dependency-groups]` in
  `pyproject.toml`, and never touch `uv.lock` by hand — let `uv` write both.
- **Frontend deps are added ONLY via `pnpm add <pkg>` / `pnpm add -D <pkg>`** (pnpm is the
  package manager; `pnpm install` / `pnpm dev` / `pnpm build`). **NEVER hand-edit**
  `package.json` dependencies or `pnpm-lock.yaml`.
- Lockfiles (`uv.lock`, `pnpm-lock.yaml`) are committed and authoritative; CI and images
  install **frozen** (`uv sync --frozen`, `pnpm install --frozen-lockfile`).

## Where things live

- `PROJECT.md` — product vision, scope (Tier 3, risky features behind config flags), grading rubric.
- `specs/constitution.md` — durable engineering principles all specs must honor.
- `specs/<feature>/` — one directory per feature; requirements + design + tasks.
- `specs/CLAUDE.md` — EARS rules and the spec-trio template.
- `backend/CLAUDE.md` — PydanticAI / FastAPI / SQLModel / pgvector conventions.
- `frontend/CLAUDE.md` — Next.js / Vercel / shadcn / PostHog conventions.
- `.claude/skills/` — reference skills (EARS, JSON contract, PydanticAI conventions) auto-loaded by specialists.
- `.claude/commands/` — `/specify` `/design` `/plan-tasks` `/implement` `/verify`.

## Operating rules

- This is the **harness** repo. Authoring harness/spec/doc content is in scope;
  do not write `backend/` or `frontend/` application code unless `/implement` is running.
- Keep this file thin. **Detailed procedures live in skills and commands, not here.**
- Never re-decide settled architecture. Open questions belong in a design.md
  "Open Decisions / Rejected Alternatives" section (e.g. Google ADK rejected,
  PageIndex deferred).
