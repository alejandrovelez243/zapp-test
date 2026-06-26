---
description: SDD gate 2 — write specs/<feature>/design.md (architecture, contracts, mermaid, Open Decisions), then STOP.
argument-hint: <feature>
---

You are the SDD **design author** for the feature `$ARGUMENTS`. This is the SECOND gate. Deliverable: `specs/$ARGUMENTS/design.md`. Do NOT write `tasks.md` or any application code.

## 0. Precondition (hard gate)
- Confirm `specs/$ARGUMENTS/requirements.md` EXISTS. If it does not, STOP and tell the user to run `/specify $ARGUMENTS` first — you cannot design without committed requirements.
- Read `specs/$ARGUMENTS/requirements.md` in full and the project `CLAUDE.md` constitution.
- Load the **pydantic-ai-conventions** and **json-contract** skills (and **ears-templates** for traceability). Use Context7 only to confirm a specific API signature you are unsure about.

## 1. Write design.md
Write `specs/$ARGUMENTS/design.md` covering:
- **Architecture overview**: how `$ARGUMENTS` fits the runtime path Next.js (Vercel) -> FastAPI (Railway) -> PydanticAI orchestrator (agent-as-tool) -> FAQ-RAG / EVENTS agents. Note where Logfire spans and PostHog events attach.
- **Component contracts**: each new/changed agent, tool, output_validator, FastAPI endpoint, or DB model — its inputs, outputs, errors, and how it reads/writes the per-turn JSON contract fields. Specify usage forwarding (`deps=ctx.deps`, `usage=ctx.usage`) and `UsageLimits` where sub-agents are involved.
- **Sequence diagrams** in **mermaid** (`sequenceDiagram`) for the primary happy path and at least one failure/degraded path (low confidence / guardrail block / unsupported language -> fallback + `needs_review=true`).
- **Data models**: Pydantic/SQLModel shapes, pgvector tables/indexes if RAG is touched, `.ics`/event shapes if events are touched.
- **Traceability table** mapping each requirement id (`$ARGUMENTS-N`) to the component(s) that satisfy it.
- **Open Decisions / Rejected Alternatives** — REQUIRED section. Always record the canonical ones where relevant:
  - **ADK-rejected**: Google ADK is a rejected alternative; ADK and PydanticAI are competing runtimes that do not compose in-process — only A2A as separate HTTP services. We use PydanticAI only.
  - **PageIndex-deferred**: RAG is pgvector-only (HNSW, hybrid-ready) now; PageIndex is a documented upgrade path, not built.
  - Plus any feature-specific decision left open, with the chosen default and the trigger that would revisit it.

## 2. STOP at the gate
- Do NOT write `tasks.md`. Task planning is the next gate (`/plan-tasks $ARGUMENTS`).
- Remind the user to **commit the design only**: `git add specs/$ARGUMENTS/design.md && git commit -m "design: $ARGUMENTS architecture"`.
- End with a one-line summary and the exact next command: `/plan-tasks $ARGUMENTS`.
