# specs/ — Spec-Driven Development rules

This directory holds the source of truth for every feature. Code is written **only**
after the governing spec is committed. The `require-spec` git hook (active once
registered — see `.claude/hooks/README.md`) blocks any `backend/`/`frontend/` code
commit until at least one committed spec trio exists in `HEAD` (a repo-level gate, not
strict per-feature). Detailed authoring guidance lives in the `ears-templates` and
`json-contract` skills.

## One feature per directory

Each feature gets its own directory with the full trio:

```
specs/<feature>/
  requirements.md   # EARS user stories + numbered, testable acceptance criteria
  design.md         # architecture, contracts, mermaid, Open Decisions / Rejected Alternatives
  tasks.md          # numbered checkbox tasks, each -> requirement id(s) + specialist
```

`specs/constitution.md` holds durable cross-feature principles; every feature must honor it.

## requirements.md — EARS notation

Every acceptance line is **numbered and testable** and maps **1:1 to an eval Case id**.
Use EARS patterns:

- **Ubiquitous** — `THE SYSTEM SHALL <req>`
- **Event-driven** — `WHEN <trigger> THE SYSTEM SHALL <req>`
- **State-driven** — `WHILE <state> THE SYSTEM SHALL <req>`
- **Unwanted** — `IF <condition> THEN THE SYSTEM SHALL <req>`
- **Optional** — `WHERE <feature included> THE SYSTEM SHALL <req>`

Pair user stories ("As a student, I want…") with the numbered acceptance criteria that
make them verifiable.

## design.md — must include Open Decisions / Rejected Alternatives

Cover architecture, component contracts, sequence diagrams (**mermaid**), and data
models. **MUST** include an explicit **"Open Decisions / Rejected Alternatives"**
section — e.g. Google ADK rejected (competing runtime, does not compose in-process with
PydanticAI; only A2A as separate HTTP services), PageIndex deferred (pgvector-only now).

## tasks.md — traceable checkboxes

Numbered checkbox tasks: `- [ ] 1. <task>`. **Each task traces to the requirement id(s)
it satisfies and to the specialist** that will implement it. Completing the tasks must
fully satisfy the requirements.

## Traceability chain (enforced)

```
acceptance line (requirements.md)  ->  task (tasks.md)  ->  eval Case id (/verify)
```

Every numbered acceptance criterion gets a task **and** a matching eval Case id, so
`/verify` can prove the requirement. No acceptance line is "done" without a passing Case.

## Order of operations

1. Commit `requirements.md` (via `/specify`).
2. Commit `design.md` (via `/design`) — including Open Decisions / Rejected Alternatives.
3. Commit `tasks.md` (via `/plan-tasks`).
4. Only then write code (via `/implement`) — **specs are committed before code.**
5. `/verify` runs the eval Cases.

Keep the canonical per-turn JSON contract and the **ES / EN / PT** language list
textually identical wherever a spec restates them (see root `CLAUDE.md`).
