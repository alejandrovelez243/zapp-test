# Orchestrator & Signal-Fusion Requirements

## Summary

The graded **API Integration & Signal Fusion** capability. The orchestrator fuses two external
APIs with the in-app signals to fill the per-turn contract's geo/fusion fields:
`detected_country` (geo-IP on the request IP), `final_normalized_text` (LLM-cleaned user text with
the resolved locale applied + relative dates resolved to the detected timezone), and
`confidence_score` (a deterministic reconciliation over all signals). Fusion runs inside a PydanticAI
tool that emits a Logfire span; reconciliation happens in the orchestrator's `output_validator`.

## Persona & job-to-be-done

As a prospective student, I want event/course times and dates shown for my country's locale and
timezone, so they are unambiguous. As the platform, I want a combined `confidence_score` and a
`needs_review` signal when sources disagree or an API fails, so low-trust turns are auditable. As the
evaluator, I want each fusion behavior to be a single testable criterion.

## In / Out of scope

In scope: a geo-IP lookup (**ipapi.co**, keyless) on the request IP → `detected_country`; **REST
Countries** enrichment → timezone + locale (pt-BR vs pt-PT, es-MX vs es-ES); `final_normalized_text`
(LLM-normalized text + locale + relative-date resolution); the deterministic `confidence_score`
reconciliation in the `output_validator`; the geo/locale fusion as a single Logfire-traced PydanticAI
tool; degraded behavior on API failure/divergence.

Out of scope (own specs): `lang_confidence` and `active_lang` (owned by `multilingual` — this feature
**reads** `lang_confidence` as one input to `confidence_score`); FAQ-RAG and EVENTS agent routing
(`faq-rag`, `events`); guardrail content (`guardrails`); the eval runner (`evaluation`).

## Config flags & values

- `geo_fusion_enabled` (flag, default **true**): false skips the geo-IP call and sets
  `detected_country=null` without error (e.g. offline/dev).
- `rest_countries_enabled` (flag, default **true**): false skips locale enrichment and applies a
  default locale for the detected country.
- Config values (resolved in design): `ipapi_base_url`, `rest_countries_base_url`, geo HTTP timeout,
  `default_locale`/`default_timezone` fallbacks.

## User Stories

- As a student, I want dates/times normalized to my locale and timezone, so they are unambiguous.
- As the platform, I want `needs_review=true` when geo fails or signals diverge, so I can audit.
- As the evaluator, I want fusion to be deterministic and testable, so `confidence_score` is measurable.

## Acceptance Criteria

1. THE SYSTEM SHALL populate `detected_country`, `final_normalized_text`, and `confidence_score` on every turn's contract.   <!-- eval: orchestrator-and-fusion-001 -->
2. WHEN a turn is processed THE SYSTEM SHALL resolve `detected_country` (ISO 3166-1 alpha-2) from a geo-IP lookup on the request IP.   <!-- eval: orchestrator-and-fusion-002 -->
3. THE SYSTEM SHALL perform the geo-IP and locale fusion inside a PydanticAI tool that emits a Logfire span.   <!-- eval: orchestrator-and-fusion-003 -->
4. WHEN `detected_country` is resolved THE SYSTEM SHALL enrich timezone and locale (e.g. pt-BR vs pt-PT, es-MX vs es-ES) via REST Countries.   <!-- eval: orchestrator-and-fusion-004 -->
5. THE SYSTEM SHALL set `final_normalized_text` to the LLM-normalized user text with the resolved locale applied.   <!-- eval: orchestrator-and-fusion-005 -->
6. WHEN the user message contains a relative temporal expression THE SYSTEM SHALL resolve it to an absolute value in the detected timezone within `final_normalized_text`.   <!-- eval: orchestrator-and-fusion-006 -->
7. WHEN the language signal agrees (lingua ≈ LLM `detected_lang`) AND geo is available AND no divergence is found THE SYSTEM SHALL set a high `confidence_score`.   <!-- eval: orchestrator-and-fusion-007 -->
8. THE SYSTEM SHALL compute `confidence_score` in the `output_validator` by deterministic reconciliation over language agreement, geo availability, and signal divergence.   <!-- eval: orchestrator-and-fusion-008 -->
9. IF the geo-IP lookup fails, times out, or returns no country THEN THE SYSTEM SHALL set `detected_country=null`, damp `confidence_score`, AND set `needs_review=true`.   <!-- eval: orchestrator-and-fusion-009 -->
10. IF the request IP is private, loopback, or invalid THEN THE SYSTEM SHALL set `detected_country=null` AND skip the external geo call.   <!-- eval: orchestrator-and-fusion-010 -->
11. IF the resolved geo locale diverges from the session's `active_lang` THEN THE SYSTEM SHALL lower `confidence_score` AND set `needs_review=true`.   <!-- eval: orchestrator-and-fusion-011 -->
12. IF the REST Countries enrichment fails THEN THE SYSTEM SHALL fall back to a default locale/timezone for the country AND set `needs_review=true`.   <!-- eval: orchestrator-and-fusion-012 -->
13. IF any fusion step raises THEN THE SYSTEM SHALL degrade to a valid nine-field contract with `needs_review=true` AND never raise to the user.   <!-- eval: orchestrator-and-fusion-013 -->
14. THE SYSTEM SHALL render `final_normalized_text` consistent with the session `active_lang` (ES/EN/PT); an unsupported language falls back to the configured fallback AND sets `needs_review=true`.   <!-- eval: orchestrator-and-fusion-014 -->
15. WHERE `geo_fusion_enabled` is false THE SYSTEM SHALL skip the geo-IP call AND set `detected_country=null` without error.   <!-- eval: orchestrator-and-fusion-015 -->
16. WHERE `rest_countries_enabled` is false THE SYSTEM SHALL skip locale enrichment AND apply the configured default locale for the detected country.   <!-- eval: orchestrator-and-fusion-016 -->
17. WHILE a session's request IP is unchanged THE SYSTEM SHALL reuse the resolved geo result rather than calling the geo-IP API again.   <!-- eval: orchestrator-and-fusion-017 -->

## Case-id map

`orchestrator-and-fusion-001..017` map 1:1 to eval `Case`s of the same id (happy + multilingual + a
geo-failure/divergence adversarial-style subset). Time-dependent criterion 006 is tested by injecting
a fixed "now" so the absolute value is deterministic. Ids are append-only.

## Non-functional / contract

- **Writes** these per-turn contract fields: `detected_country` (ISO 3166-1 alpha-2 or null),
  `final_normalized_text`, `confidence_score`, and `needs_review`. **Reads** the request IP, the user
  message, `active_lang` and `lang_confidence` (owned by `multilingual`) as fusion inputs.
- Two external APIs: **ipapi.co** (geo-IP, keyless) and **REST Countries** (locale/timezone), both
  called inside a PydanticAI tool over the shared `httpx` client → captured as Logfire spans.
- Languages: `final_normalized_text` and the reply stay in the session `active_lang` (ES/EN/PT);
  unsupported → fallback + `needs_review=true`.
- Reconciliation: agreement → high `confidence_score`; divergence / geo-fail / unsupported language →
  damped `confidence_score` + `needs_review=true` (deterministic rules, no weighted formula).
- Resilience: every external call is timeout-bounded; any failure degrades to a valid contract with
  `needs_review=true`, never a 5xx.
