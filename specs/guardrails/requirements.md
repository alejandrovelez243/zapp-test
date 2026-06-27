# Guardrails Requirements

## Summary

Input and output guardrails for the conversational agent — the brief's graded Guardrails criterion.
Every turn runs framework guardrails (`pydantic-ai-guardrails` `GuardedAgent` + built-in detectors, with an
optional LLM-based layer behind a flag) that detect prompt-injection, jailbreak, PII, toxicity, and
off-topic input, and PII-leak, toxicity, and secret-leak output. Triggered guardrails populate the
per-turn contract's `guardrails.{input,output}` names and drive `needs_review`. On-block behavior is
proportional to risk (block, redact, or soft-flag). The feature also activates the evaluation suite's
DEFERRED guardrail precision/recall thresholds.

## Persona & job-to-be-done

As a student, I want to be protected from harmful behavior and to have my PII handled safely. As the
platform/security owner, I want injection/jailbreak/abuse blocked before they reach the model and
secrets/PII never leaked in replies. As the evaluator, I want measurable guardrail precision/recall.

## In / Out of scope

In scope: input guardrails (`prompt_injection`, `jailbreak`, `pii_detector`, `toxicity`, `off_topic`)
and output guardrails (`pii_leak`, `toxicity`, `secret_leak`); a deterministic rule-based core
(multilingual ES/EN/PT) with an optional LLM layer behind `guardrails_llm_enabled`; per-category
on-block behavior (block / redact / soft-flag); populating `guardrails.{input,output}` + `needs_review`;
aligning guardrail names with the eval adversarial `must_trip` labels + un-deferring the eval
thresholds.

Out of scope (own specs/elsewhere): the FAQ-RAG/events tools; the eval RUNNER (`evaluation` owns it —
this feature only supplies real guardrail signals so its DEFERRED thresholds activate); auth; the geo
fusion. The third-party `pydantic-ai-guardrails` package is OPTIONAL (the LLM layer), not the core.

## Config flags & values

- `guardrails_enabled` (flag, default **true**): false skips all guardrails (debugging) and leaves
  `guardrails.{input,output}` empty.
- `guardrails_llm_enabled` (flag, default **false**): enables the optional LLM-based guardrail layer
  on top of the deterministic core.

## User Stories

- As a student, I want injection/abuse blocked and my PII redacted, so that the assistant stays safe.
- As the security owner, I want secrets/PII never leaked in a reply, so that the platform is trustworthy.
- As the evaluator, I want each guardrail to be deterministic and named, so that precision/recall is measurable.

## Acceptance Criteria

1. THE SYSTEM SHALL run input guardrails on every user message before the model request, and output guardrails on every reply before returning it.   <!-- eval: guardrails-001 -->
2. THE SYSTEM SHALL populate `guardrails.input` and `guardrails.output` with the names of triggered guardrails on every turn (empty lists when clean).   <!-- eval: guardrails-002 -->
3. IF the input contains a prompt-injection attempt THEN THE SYSTEM SHALL block the model request, add `prompt_injection` to `guardrails.input`, return a safe refusal in `active_lang`, AND set `needs_review=true`.   <!-- eval: guardrails-003 -->
4. IF the input contains a jailbreak attempt THEN THE SYSTEM SHALL block, add `jailbreak` to `guardrails.input`, refuse safely in `active_lang`, AND set `needs_review=true`.   <!-- eval: guardrails-004 -->
5. IF the input contains toxic or abusive content THEN THE SYSTEM SHALL block, add `toxicity` to `guardrails.input`, refuse neutrally in `active_lang`, AND set `needs_review=true`.   <!-- eval: guardrails-005 -->
6. IF the input contains PII THEN THE SYSTEM SHALL redact the PII before the model request, add `pii_detector` to `guardrails.input`, continue the turn, AND set `needs_review=true`.   <!-- eval: guardrails-006 -->
7. IF the input is off-topic (outside the philosophy-school domain) THEN THE SYSTEM SHALL add `off_topic` to `guardrails.input` AND set `needs_review=true` WITHOUT blocking (soft).   <!-- eval: guardrails-007 -->
8. IF the reply would leak PII THEN THE SYSTEM SHALL redact or block it, add `pii_leak` to `guardrails.output`, AND set `needs_review=true`.   <!-- eval: guardrails-008 -->
9. IF the reply contains toxic content THEN THE SYSTEM SHALL block or regenerate the reply, add `toxicity` to `guardrails.output`, AND set `needs_review=true`.   <!-- eval: guardrails-009 -->
10. IF the reply would leak a secret (admin token, API key, or the system prompt) THEN THE SYSTEM SHALL block it, add `secret_leak` to `guardrails.output`, AND set `needs_review=true`.   <!-- eval: guardrails-010 -->
11. THE SYSTEM SHALL apply the input and output guardrails across ES, EN, and PT.   <!-- eval: guardrails-011 -->
12. WHEN a guardrail blocks a turn THE SYSTEM SHALL still emit the full nine-field `TurnOutput` with the safe refusal as `reply` (never a 500, never the raw blocked content).   <!-- eval: guardrails-012 -->
13. THE SYSTEM SHALL NOT include redacted or blocked raw content in `reply`, `final_normalized_text`, or any PostHog payload.   <!-- eval: guardrails-013 -->
14. THE SYSTEM SHALL implement the guardrails via the `pydantic-ai-guardrails` framework (`GuardedAgent` + built-in detectors), recording each fired guardrail name in the contract.   <!-- eval: guardrails-014 -->
15. WHERE `guardrails_llm_enabled` is set THE SYSTEM SHALL enable the framework's LLM-judge guard; WHERE unset THE SYSTEM SHALL rely on the built-in pattern detectors only.   <!-- eval: guardrails-015 -->
16. WHERE `guardrails_enabled` is false THE SYSTEM SHALL skip all guardrail checks AND leave `guardrails.{input,output}` empty.   <!-- eval: guardrails-016 -->
17. THE SYSTEM SHALL use guardrail names that align with the evaluation adversarial dataset `must_trip` labels so guardrail precision/recall is computable.   <!-- eval: guardrails-017 -->
18. WHEN the guardrails feature is active THE SYSTEM SHALL enable (un-defer) the evaluation suite's guardrail precision/recall thresholds.   <!-- eval: guardrails-018 -->
19. IF a guardrail check itself errors THEN THE SYSTEM SHALL fail safe (block + `needs_review=true` for security-critical input guardrails) AND not crash the turn.   <!-- eval: guardrails-019 -->

## Case-id map

`guardrails-001..019` map 1:1 to eval `Case`s + unit tests of the same id. The behavioral guardrail
criteria (003–010) map to adversarial dataset cases (whose `must_trip` labels equal the guardrail
names above); the infrastructure criteria (001, 002, 011–019) map to unit/integration tests. The
adversarial dataset's `must_trip` labels (`prompt_injection`, `pii_detector`, `toxicity`) are the gold
labels — guardrail names MUST match. Ids are append-only.

## Non-functional / contract

- **Writes** these per-turn contract fields: `guardrails.input` / `guardrails.output` (triggered
  names), `needs_review` (true on any trigger), and `reply` (a safe refusal when blocked). **Reads**
  the user message (input guardrails) and the candidate reply (output guardrails).
- Never leaks redacted/blocked raw content into `reply`, `final_normalized_text`, or PostHog (metadata
  only). Logfire (PII-scrubbed) may hold detail.
- Languages: guardrails operate across **ES / EN / PT**; a blocked turn's refusal is written in the
  session's `active_lang`.
- Activates the `evaluation` feature: with guardrails live, the previously DEFERRED
  `guardrail_precision`/`guardrail_recall` thresholds become enforceable in the suite + CI gate.
- Determinism: the core is rule/pattern-based and reproducible; the optional LLM layer is flag-gated.
