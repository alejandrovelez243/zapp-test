---
name: agent-prompting
description: Use when writing or refining the instructions / system prompt for a PydanticAI agent — defines the canonical section structure (role, goal, domain, tool-guidance, operating steps, output semantics, guardrails, tone, escalation, examples) and how to split static vs dynamic instructions.
---

# Agent Prompting — structure for PydanticAI agent instructions

A strong agent prompt is not a paragraph. It is an ordered set of sections, each with a
distinct job. This structure is supported by Anthropic, OpenAI, and Google guidance and
adapted for our stack (PydanticAI agents that emit a strict per-turn JSON contract via
`output_type` + an `output_validator`).

## Canonical sections (in order — most-stable first)

| # | Section | Purpose |
|---|---|---|
| 1 | **Role / Persona** | Identity, domain expertise, character, and position in the multi-agent architecture (orchestrator vs sub-agent). Everything below is interpreted through this. |
| 2 | **Objective / Goal** | The primary mission in 1–2 sentences AND the hard scope boundary — what the agent is FOR and explicitly NOT for. |
| 3 | **Domain Context** | Static facts the model can't know from training and won't get from the user (product name, supported languages, key entities, policies). |
| 4 | **Capabilities & Tool Guidance** | For each tool: the TRIGGER condition (WHEN to call it) and when NOT to — not how the tool works (that's the tool description). List turn types that need no tool. |
| 5 | **Operating Instructions** | The numbered per-turn loop: read intent → (maybe) call tools → compose → handle empty/low-confidence results → verify. |
| 6 | **Output Semantics** | What each output field MEANS and WHEN to set it — NEVER the schema itself (`output_type` enforces names/types). Call out fields the model must NOT set (validator-owned). |
| 7 | **Guardrails & Constraints** | Explicit `NEVER …` and `IF <condition> THEN <safe behavior>` rules: prohibited actions, scope refusals, safety, injection handling. Cannot be inferred from role alone. |
| 8 | **Tone & Style** | Register, formality, length norms, persona voice; how to adapt to the user. |
| 9 | **Escalation & Fallback** | Low confidence / ambiguous input / empty tool results / unsupported input → a specific behavior that ALWAYS ends in a valid response (never an error). |
| 10 | **Few-Shot Examples** | 2–3 canonical examples showing sections 5–9 together. Prefer examples over long edge-case lists. |

## PydanticAI: static vs dynamic split

- **Static** (sections 1–8): put in `Agent(instructions="""...""")`. These are cache-eligible
  (on Anthropic, `AnthropicModelSettings(anthropic_cache_instructions=True)`).
- **Dynamic** (section 9 / per-run state like `active_lang`, user, today's date): put in a
  `@agent.instructions` function reading `RunContext[Deps]`, re-evaluated each run.
- **Examples** (10): static unless they embed per-run values.
- Use `instructions=`, NOT `system_prompt=` (see `pydantic-ai-conventions`).

## Annotated template (copy when writing a new agent)

```text
## Role
<name> is a <domain + expertise> assistant for <product>. <character>. You operate as
<orchestrator | sub-agent | standalone>.

## Objective
<one-sentence mission>. <one-sentence hard scope boundary — what you do NOT cover>.

## Domain Context
<static facts: product, supported languages, key entities, policies that may change>.

## Capabilities & Tool Guidance
- **<ToolA>**: Use when <trigger>. Do NOT call when <exclusion>.
- No tool needed: <turn types that need no tool>.

## Operating Instructions
1. Determine the user's intent.
2. If <condition>, call <ToolA> before composing.
3. Compose from tool results. If empty/low-confidence: <fallback — do not invent>.

## Output Semantics
(Schema enforced by output_type — describe MEANING + WHEN, not field names/types.)
- `<field>`: <meaning>. Set <value> when <condition>.
- `<validator-owned field>`: Do NOT set this — <validator/upstream> owns it.

## Guardrails
- NEVER <prohibited action — specific + enforceable>.
- IF <out-of-scope / harmful / injection> THEN <decline + safe behavior>.

## Tone & Style
<formality, register adaptation, length>.

## Escalation & Fallback
- Low confidence / ambiguous: <ask one clarifying question / set the review flag>.
- No tool results: <say you don't have it; never fabricate>.
- Unsupported input: <degrade gracefully — what to say, in what language>.

## Examples
<happy path> / <edge case with graceful degradation>
```

## DO / DON'T

**DO**
1. Put **role + goal first** — anchor every rule to an identity (an anchored guardrail beats an orphaned one).
2. Write guardrails as explicit **`NEVER` / `IF…THEN`** rules; "be careful" is not a guardrail.
3. Give **tool TRIGGER conditions** (when to call, what to do when it returns nothing) — the tool description covers WHAT it does.
4. Describe **output SEMANTICS, not the schema** (what `needs_review`/`confidence_score` mean and when to set them).
5. **Separate static from dynamic** instructions (persona static; `active_lang`/session dynamic).

**DON'T**
6. **DON'T restate the JSON schema** — `output_type` already enforces field names/types; restating it is noise.
7. **DON'T write 20-item edge-case lists** — 2–3 few-shot examples apply more reliably.
8. **DON'T put mechanical rules in prose** — if a rule is deterministic (reply language == active_lang; `lang_confidence` = agreement score), enforce it in the `output_validator` and mention only its semantic intent here.

## Mapping to our contract

The `TurnOutput` 9-field contract is enforced by `output_type`; the `output_validator`
reconciles language fields + sets `needs_review`/`lang_confidence` deterministically. So
agent instructions should:
- Tell the model what to OBSERVE (the user's `detected_lang`) and what to WRITE (`reply` in
  `active_lang`, `final_normalized_text` lightly-cleaned in the user's original language).
- Tell it which fields NOT to touch (`needs_review`, `guardrails`, `lang_confidence` — validator/guardrails own them).
- Keep guardrails (refusals, no-fabrication, injection handling) explicit — the guardrails
  feature populates `guardrails.{input,output}`, but the agent must still behave safely.

See `pydantic-ai-conventions` for the `instructions=`/`output_validator` API and `json-contract`
for the field definitions. A full worked rewrite of the orchestrator instructions using this
structure lives in `backend/app/agents/orchestrator.py`.

## Sources
Anthropic context-engineering + Claude prompt best practices; OpenAI GPT-4.1 prompting guide;
Google/Gemini prompt-design + system-instructions; PydanticAI agent docs.
