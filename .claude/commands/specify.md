---
description: SDD gate 1 — interview and write specs/<feature>/requirements.md in EARS, then STOP (commit specs only).
argument-hint: <feature>
---

You are the SDD **spec author** for the feature `$ARGUMENTS`. This is the FIRST gate of Spec-Driven Development. The git hook enforces specs-before-code, so your only deliverable is `specs/$ARGUMENTS/requirements.md`. Do NOT design, plan, or write any application code.

## 0. Read the constitution and prior art
- Read `CLAUDE.md` (and any nested `CLAUDE.md`) for the project constitution: the canonical per-turn JSON contract, supported languages ES/EN/PT, the resolved architecture (Next.js -> FastAPI -> PydanticAI orchestrator routing to FAQ-RAG + EVENTS agents), and the guardrail/eval/signal-fusion decisions.
- Load the **ears-templates** skill — it is mandatory for the acceptance-criteria notation.
- If `specs/$ARGUMENTS/requirements.md` already exists, read it and treat this run as a revision, not a fresh start.
- Skim sibling specs under `specs/*/requirements.md` to keep Case-id numbering and vocabulary consistent across features.

## 1. Interview the stakeholder
Use **AskUserQuestion** to resolve every ambiguity BEFORE writing. Ask in focused batches; do not invent scope. Cover at minimum:
- The user/persona and the job-to-be-done for `$ARGUMENTS`, and what is explicitly OUT of scope (Tier-3 vision means risky parts ship behind config flags — confirm which flags).
- Success criteria and failure/degraded behavior, including how this feature touches the per-turn contract fields (`needs_review`, `confidence_score`, `lang_confidence`, `guardrails`, `active_lang` fallback for unsupported languages).
- Multilingual expectations (ES/EN/PT) and the unsupported-language fallback.
- Guardrail, auth (admin-token vs anonymous session), and data-lifecycle constraints relevant to this feature.
- Which signals (geo-IP, lingua detector, REST Countries, LLM detected_lang) participate, if any.
Stop interviewing once you can write every acceptance line as testable.

## 2. Write requirements.md
Write `specs/$ARGUMENTS/requirements.md` with:
- A short **Introduction** (problem, persona, in/out of scope, config flags).
- **User stories** ("As a <role>, I want <capability>, so that <benefit>").
- **Acceptance criteria** in strict EARS notation (per the ears-templates skill):
  - Ubiquitous `THE SYSTEM SHALL <req>`
  - Event-driven `WHEN <trigger> THE SYSTEM SHALL <req>`
  - State-driven `WHILE <state> THE SYSTEM SHALL <req>`
  - Unwanted `IF <condition> THEN THE SYSTEM SHALL <req>`
  - Optional `WHERE <feature included> THE SYSTEM SHALL <req>`
- Every acceptance line is **numbered** (e.g. `$ARGUMENTS-1`, `$ARGUMENTS-2`) and **testable**, and maps **1:1 to a future eval Case id**. Add a "Case-id map" note making that mapping explicit.
- A **Non-functional / contract** subsection asserting which per-turn JSON contract fields this feature reads or writes, and the ES/EN/PT + fallback requirement where relevant.

## 3. STOP at the gate
- Do NOT write `design.md` or `tasks.md`. Design is the next gate (`/design $ARGUMENTS`).
- Remind the user to **commit specs-only** now, e.g. `git add specs/$ARGUMENTS/requirements.md && git commit -m "specify: $ARGUMENTS requirements (EARS)"`. The pre-commit hook rejects code in a specify commit.
- End with a one-line summary of the requirements written and the exact next command: `/design $ARGUMENTS`.
