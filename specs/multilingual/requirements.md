# Multilingual Requirements

## Summary

The platform's conversational agent must detect the language a student writes in, reply in that
language, and stay coherent in one language per session (ES / EN / PT), degrading gracefully on
unsupported languages. This feature owns the **language** fields of the per-turn JSON contract
(`detected_lang`, `active_lang`, `lang_confidence`) and the language-related `needs_review`
triggers. It fuses a deterministic `lingua` detector with the LLM's own `detected_lang` to produce
`lang_confidence` as an agreement score. Country/geo signals (`detected_country`,
`final_normalized_text`, locale variants) are out of scope here and specified in
`orchestrator-and-fusion`.

## In / Out of scope

In scope: language detection (lingua ⊕ LLM), first-turn `active_lang` lock and session coherence,
`lang_confidence` agreement score, unsupported-language fallback + `needs_review`, low-confidence
clarification turn, short-input stability, and flag-gated language auto-switch.

Out of scope: geo-IP / `detected_country` / REST Countries locale variants (pt-BR vs pt-PT) and
`final_normalized_text` normalization → `orchestrator-and-fusion`; guardrail content/taxonomy →
`guardrails`; the eval harness itself → `evaluation`; UI-chrome translation → frontend.

## Config flags & config values

- `lang_autoswitch` (flag, default **off**): off = hard-lock `active_lang` for the whole session;
  on = allow a switch after ≥2 consecutive turns in another supported language.
- Config values (resolved in design.md, not flags): `lang_confidence_min` (clarification threshold),
  `min_input_tokens` (short-input floor), `fallback_lang = en`.

## User Stories

- As a prospective student, I want replies in the language I wrote in, so that I can understand them.
- As a student, I want the assistant to stay in one language per session, so that the conversation
  does not flip-flop confusingly.
- As a student writing in an unsupported language, I want a graceful fallback that tells me which
  languages are supported, so that I am not stuck.
- As the evaluation system, I want each language behavior to be a single testable criterion, so that
  language fidelity is measurable.

## Acceptance Criteria

1. THE SYSTEM SHALL emit the per-turn JSON contract with all nine fields populated on every chat turn.   <!-- eval: multilingual-001 -->
2. THE SYSTEM SHALL set `detected_lang` to the ISO 639-1 code of the language the user wrote in.          <!-- eval: multilingual-002 -->
3. THE SYSTEM SHALL set `active_lang` to one of `es`, `en`, or `pt` on every response.                    <!-- eval: multilingual-003 -->
4. WHEN the first user message of a session arrives THE SYSTEM SHALL lock `active_lang` to the detected supported language.   <!-- eval: multilingual-004 -->
5. WHEN a user message arrives THE SYSTEM SHALL compute `lang_confidence` as the agreement score between the lingua detector and the LLM `detected_lang`.   <!-- eval: multilingual-005 -->
6. WHEN a user message's `detected_lang` differs from the locked `active_lang` THE SYSTEM SHALL reply in `active_lang` and recompute `lang_confidence`.   <!-- eval: multilingual-006 -->
7. WHILE a session is locked to an `active_lang` THE SYSTEM SHALL render every `reply` in that language until the session ends or an allowed switch occurs.   <!-- eval: multilingual-007 -->
8. IF the detected language is not `es`/`en`/`pt` AND the session is already locked to a supported `active_lang` THEN THE SYSTEM SHALL keep the existing `active_lang` AND set `needs_review=true`.   <!-- eval: multilingual-008 -->
9. IF the detected language is not `es`/`en`/`pt` AND it is the first turn THEN THE SYSTEM SHALL set `active_lang` to the configured fallback (`en`) AND set `needs_review=true`.   <!-- eval: multilingual-009 -->
10. IF `lang_confidence` is below the configured threshold THEN THE SYSTEM SHALL keep the current `active_lang`, ask the user to confirm their language in the `reply`, AND set `needs_review=true`.   <!-- eval: multilingual-010 -->
11. IF a user message is shorter than the configured minimum length THEN THE SYSTEM SHALL retain the current `active_lang` AND SHALL NOT trigger a language switch.   <!-- eval: multilingual-011 -->
12. IF language detection fails THEN THE SYSTEM SHALL fall back to the LLM `detected_lang`, set `lang_confidence` to a low value, AND set `needs_review=true`.   <!-- eval: multilingual-012 -->
13. WHERE language auto-switch is enabled THE SYSTEM SHALL switch `active_lang` to a new supported language only after the user writes in that language for at least two consecutive turns.   <!-- eval: multilingual-013 -->
14. WHERE language auto-switch is disabled THE SYSTEM SHALL keep the first-turn `active_lang` for the entire session regardless of later turns' `detected_lang`.   <!-- eval: multilingual-014 -->

## Case-id map

Each acceptance line maps 1:1 to a `pydantic-evals` `Case` of the same id (`multilingual-001` …
`multilingual-014`) in the `multilingual` dataset. No orphans in either direction; ids are append-only
(never renumbered) and are referenced from `tasks.md` and the eval dataset.

## Non-functional / contract

- **Writes** these per-turn contract fields: `detected_lang`, `active_lang`, `lang_confidence`,
  `needs_review`, and `reply` (in `active_lang`).
- **Reads** session state: the locked `active_lang` and recent turns from `message_history`.
- **Does not set** `detected_country`, `final_normalized_text`, or `confidence_score` (owned by
  `orchestrator-and-fusion`) — but every turn still emits the full nine-field contract (criterion 1).
- Supported languages: **ES, EN, PT**; unsupported → fallback per criteria 8–9 + `needs_review=true`.
- Coherence: at most one `active_lang` switch decision per turn; default behavior is a hard session
  lock unless `lang_autoswitch` is enabled.
