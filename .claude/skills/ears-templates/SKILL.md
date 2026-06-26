---
name: ears-templates
description: Use when writing or reviewing requirements.md acceptance criteria in EARS notation for SDD specs
---

# EARS Templates for requirements.md

EARS (Easy Approach to Requirements Syntax) constrains every requirement to one of
five sentence shapes. The shape forces an author to state the trigger, the state,
and the response explicitly, which makes each line **testable** and removes the
ambiguity that free-prose requirements smuggle in. In this project every numbered
acceptance line maps **1:1 to an eval Case id** in `pydantic-evals`, so the wording
has to be precise enough to assert against.

Domain reminder: a Philosophy School platform. The product supports **ES, EN, PT**
at runtime; unsupported language -> set `active_lang` to the configured fallback AND
`needs_review=true`, degrade gracefully. Every turn emits the per-turn JSON contract
(`reply`, `detected_lang`, `active_lang`, `lang_confidence`, `final_normalized_text`,
`detected_country`, `confidence_score`, `needs_review`, `guardrails`).

## The Iron Rule

**Every acceptance line is numbered, uses exactly one EARS pattern, is independently
testable by a single assertion, and maps 1:1 to an eval `Case` id** — no orphans in
either direction. If you cannot write one pydantic-evals `Case` that passes or fails
on a single criterion, the criterion is wrong: split it, sharpen it, or make it
measurable. Carry the id inline (e.g. `<!-- eval: faq-rag-003 -->`) so the mapping is
mechanically checkable. Number sequentially and never renumber on edit — ids are
referenced from tasks.md and the eval dataset; append and deprecate instead.

## The 5 EARS patterns

Keywords are UPPERCASE so they are greppable. THE SYSTEM SHALL is the response clause
in every pattern.

### 1. Ubiquitous — always-on, no trigger
Template: `THE SYSTEM SHALL <requirement>`
Use for invariants that hold on every turn.

- THE SYSTEM SHALL emit the per-turn JSON contract with all nine fields populated on every chat turn.
- THE SYSTEM SHALL set `active_lang` to one of ES, EN, or PT on every response.

### 2. Event-driven — `WHEN` a trigger occurs
Template: `WHEN <trigger> THE SYSTEM SHALL <requirement>`
Use for behavior provoked by a discrete event or input.

- WHEN a user sends a message whose detected language differs from the locked `active_lang` THE SYSTEM SHALL keep responding in `active_lang` and recompute `lang_confidence`.
- WHEN the events agent completes an enrollment THE SYSTEM SHALL return a `.ics` file with event times localized to the user's resolved timezone.

### 3. State-driven — `WHILE` in a state
Template: `WHILE <state> THE SYSTEM SHALL <requirement>`
Use for behavior that persists for the duration of a condition.

- WHILE a session is locked to `active_lang=pt` THE SYSTEM SHALL render all replies and the `.ics` summary in Portuguese until the session ends.
- WHILE document ingestion for an uploaded doc is still running THE SYSTEM SHALL exclude that document's chunks from FAQ-RAG retrieval.

### 4. Unwanted-behavior — `IF ... THEN`
Template: `IF <condition> THEN THE SYSTEM SHALL <requirement>`
Use for error handling, guardrail trips, and degradation. This pattern is where
most guardrail and resilience criteria live.

- IF an input guardrail detects PII or prompt injection THEN THE SYSTEM SHALL list the triggered guardrail name in `guardrails.input` and redact the content before the model request.
- IF the detected language is unsupported (not ES/EN/PT) THEN THE SYSTEM SHALL set `active_lang` to the configured fallback AND set `needs_review=true`.

### 5. Optional — `WHERE` a feature is included
Template: `WHERE <feature is included> THE SYSTEM SHALL <requirement>`
Use for behavior gated behind a config flag (Tier 3 risky features live here).

- WHERE hybrid retrieval is enabled THE SYSTEM SHALL combine pgvector cosine scores with keyword scores before ranking FAQ-RAG chunks.
- WHERE the geo-IP signal fusion flag is enabled THE SYSTEM SHALL enrich `detected_country` with REST Countries timezone/locale data (pt-BR vs pt-PT, es-ES vs es-MX).

## requirements.md structure

```markdown
# <Feature> Requirements

## Summary
<2-4 sentences: what this feature does and why it exists.>

## User Stories
- As a <role> I want <goal> so that <benefit>.
- As a prospective student I want to ask FAQs in my own language so that I get answers I understand.
- As an admin I want to upload and delete docs so that the FAQ corpus stays current.

## Acceptance Criteria
1. WHEN <trigger> THE SYSTEM SHALL <requirement>.        <!-- eval: faq-rag-001 -->
2. IF <condition> THEN THE SYSTEM SHALL <requirement>.   <!-- eval: faq-rag-002 -->
3. THE SYSTEM SHALL <requirement>.                       <!-- eval: faq-rag-003 -->
```

Roles on this platform: **student** (anonymous chat, enrolls), **admin** (token-gated
doc/event management), **evaluator/system** (runtime eval + guardrails).

Line-level rules:
- One requirement per line. If a line needs "and" between two distinct behaviors, split it — the only exception is a contract-mandated compound like fallback-lang AND `needs_review=true`, which is one inseparable observable rule.
- Reference contract fields by their exact names; restate the JSON contract and the ES/EN/PT language list textually identically to the canonical source.
- Requirements state observable behavior; the library, table, and tool choices belong in design.md.

## Worked example (multilingual feature)

```markdown
## User Stories
- As a student I want replies in the language I wrote in so that I can understand them.

## Acceptance Criteria
1. WHEN a student message arrives THE SYSTEM SHALL fuse the lingua detector with the
   LLM `detected_lang` to compute `lang_confidence` as an agreement score.   <!-- eval: multilingual-001 -->
2. WHILE the session is locked to an `active_lang` THE SYSTEM SHALL return every
   `reply` in that language regardless of one turn's `detected_lang`.        <!-- eval: multilingual-002 -->
3. IF the detected language is not ES/EN/PT THEN THE SYSTEM SHALL set `active_lang`
   to the configured fallback AND set `needs_review=true`.                   <!-- eval: multilingual-003 -->
```

Each line is one EARS pattern, names the exact contract field it asserts, and has a
matching `Case` (`multilingual-001..003`) in the eval dataset.

## Anti-patterns to avoid

1. **Vague, unmeasurable language.** "THE SYSTEM SHALL respond quickly / handle errors gracefully / be user-friendly." No assertion passes or fails it. Bind it to a number or an observable field: "WHEN p95 turn latency exceeds 4000 ms THE SYSTEM SHALL set `needs_review=true`."
2. **Stating a solution instead of a requirement.** "THE SYSTEM SHALL call ipinfo.io inside a PydanticAI tool." That is design, not acceptance. Write the observable behavior ("THE SYSTEM SHALL populate `detected_country` from a geo-IP signal"); the implementation choice lives in design.md.
3. **Compound / multi-trigger lines that cannot map to one Case.** "WHEN a user enrolls and uploads a doc and switches language THE SYSTEM SHALL ...". Three triggers, three behaviors, untestable as one assertion and impossible to map 1:1 to a single eval Case. Split into separate numbered lines, each with its own eval id.

## Review checklist

- Does every line start with exactly one EARS keyword (THE SYSTEM SHALL / WHEN / WHILE / IF…THEN / WHERE)?
- Is each line atomic, observable, and falsifiable by a single assertion?
- Does each line carry an `eval:` id that exists as a `Case` in the feature dataset, and vice versa (no orphans)?
- Are config-gated behaviors written as WHERE, not buried in prose?
- Do guardrail, multilingual, and contract-field requirements name the exact JSON field they affect (`active_lang`, `needs_review`, `guardrails.input`, ...)?
