# Frontend Shell Requirements

## Summary

The conversational product currently ships a bare `create-next-app` scaffold (inline CSS, no design
system, no i18n, no tests). `frontend-shell` replaces it with the real **chat surface**: a
typographically-led, classical (ancient-Greece-inspired) UI that renders the per-turn JSON contract
calmly, localizes its own chrome to the session `active_lang` (ES / EN / PT), and is accessible and
tested. The frontend is a **read-only consumer** of the contract — it sends only `session_id` +
`message` and never computes contract fields. Admin management, enrollment/`.ics`, token-by-token
streaming, and product analytics are explicitly out of scope here.

## In / Out of scope

In scope: the anonymous chat surface (composer + transcript + `session_id`); calm rendering of the
contract fields a student should see (`reply`, `active_lang`, `detected_lang` mismatch hint,
`needs_review`, `guardrails`); a flag-gated debug disclosure for the remaining contract fields;
runtime i18n of UI chrome mirroring `active_lang` with EN fallback; the classical visual system
(typography, restrained palette + one accent, Greek-key hairlines, calm motion); accessibility
(WCAG AA, keyboard, `aria-live`, reduced-motion); and frontend component tests + CI lint/typecheck.

Out of scope: admin-token-gated document/event management UI → later feature; event enrollment and
`.ics` download → later feature; **product analytics / PostHog → backend-only, NOT wired in the
frontend** (per stakeholder decision; supersedes the PostHog mandate in `frontend/CLAUDE.md`, which
will be corrected separately); token-by-token streaming → deferred, depends on a backend SSE
endpoint that does not yet exist; the backend computation of any contract field → owned by
`multilingual`, `guardrails`, `orchestrator-and-fusion`.

## Config flags & config values

- `details_disclosure` (flag, env `NEXT_PUBLIC_SHOW_DETAILS`, default **off**): off = the debug
  contract fields are never rendered; on = a collapsible disclosure exposes them per turn.
- Config values (resolved in design.md, not flags): `fallback_lang = en` (UI-chrome fallback),
  `api_base` (`NEXT_PUBLIC_API_URL`, proxied via a Next rewrite — never a secret).

## User Stories

- As a prospective student, I want to ask questions in a calm, readable chat, so that the
  experience feels considered rather than like a generic dashboard.
- As a student, I want the interface to speak the language the session locked to, so that the whole
  experience is coherent in my language.
- As a student, I want low-confidence or filtered turns flagged quietly (not alarmingly), so that I
  stay informed without being scared off.
- As an operator/debugger, I want the raw signal fields available behind an opt-in disclosure, so
  that I can inspect a turn without cluttering the student view.
- As a keyboard or screen-reader user, I want full operability and announced replies, so that the
  chat is usable without a mouse or sight.
- As the evaluation system, I want each UI behavior to be a single testable criterion, so that the
  shell is measurable.

## Acceptance Criteria

1. THE SYSTEM SHALL present a single-column chat surface with a message composer and a transcript of prior turns in the session.   <!-- eval: frontend-shell-001 -->
2. THE SYSTEM SHALL generate an anonymous `session_id` for the browser session, persist it across turns, and send it on every chat request.   <!-- eval: frontend-shell-002 -->
3. WHEN the student submits a non-empty message THE SYSTEM SHALL append the student's message to the transcript AND send it with the `session_id` to the chat endpoint.   <!-- eval: frontend-shell-003 -->
4. WHEN the chat endpoint returns a per-turn contract THE SYSTEM SHALL render its `reply` as the assistant's turn in the transcript.   <!-- eval: frontend-shell-004 -->
5. WHILE a chat request is in flight THE SYSTEM SHALL show a calm pending indicator AND prevent a second concurrent submission.   <!-- eval: frontend-shell-005 -->
6. IF a chat request fails or returns a non-contract response THEN THE SYSTEM SHALL show a localized error affordance AND SHALL preserve the existing transcript.   <!-- eval: frontend-shell-006 -->
7. WHEN the student presses Enter in the composer THE SYSTEM SHALL submit the message, AND WHEN the student presses Shift+Enter THE SYSTEM SHALL insert a newline instead.   <!-- eval: frontend-shell-007 -->
8. WHEN a turn's contract has `needs_review=true` THE SYSTEM SHALL mark that turn with a quiet hairline/side-rule and an accessible tooltip, and SHALL NOT use a red alarm banner.   <!-- eval: frontend-shell-008 -->
9. THE SYSTEM SHALL display the session `active_lang` as a discreet, non-intrusive indicator.   <!-- eval: frontend-shell-009 -->
10. WHEN a turn's `detected_lang` differs from `active_lang` THE SYSTEM SHALL surface a quiet hint that the session language is locked.   <!-- eval: frontend-shell-010 -->
11. WHEN a turn's `guardrails.input` or `guardrails.output` is non-empty THE SYSTEM SHALL show a calm "filtered" affordance on that turn AND SHALL NOT expose raw guardrail internals.   <!-- eval: frontend-shell-011 -->
12. WHERE the details disclosure is enabled THE SYSTEM SHALL provide a collapsible, keyboard-operable control exposing `lang_confidence`, `confidence_score`, `final_normalized_text`, and `detected_country` for a turn.   <!-- eval: frontend-shell-012 -->
13. WHERE the details disclosure is disabled THE SYSTEM SHALL NOT render `lang_confidence`, `confidence_score`, `final_normalized_text`, or `detected_country`.   <!-- eval: frontend-shell-013 -->
14. THE SYSTEM SHALL render all UI chrome copy (labels, placeholders, controls, errors) in the session `active_lang`, one of ES, EN, or PT.   <!-- eval: frontend-shell-014 -->
15. WHEN `active_lang` changes between turns THE SYSTEM SHALL update the UI chrome copy to the new `active_lang`.   <!-- eval: frontend-shell-015 -->
16. IF `active_lang` is not one of ES, EN, or PT THEN THE SYSTEM SHALL render UI chrome in the configured fallback language (`en`).   <!-- eval: frontend-shell-016 -->
17. THE SYSTEM SHALL present a typographically-led classical aesthetic: a serif display face for headings, a restrained near-monochrome ink-on-paper palette with a single accent colour, and Greek-key hairline motifs.   <!-- eval: frontend-shell-017 -->
18. IF the user agent requests reduced motion (`prefers-reduced-motion: reduce`) THEN THE SYSTEM SHALL disable non-essential animation.   <!-- eval: frontend-shell-018 -->
19. THE SYSTEM SHALL announce newly-arrived assistant turns to assistive technology via an `aria-live` region.   <!-- eval: frontend-shell-019 -->
20. THE SYSTEM SHALL be fully keyboard operable for composing, submitting, and toggling the details disclosure, with a visible focus indicator on every interactive element.   <!-- eval: frontend-shell-020 -->
21. THE SYSTEM SHALL meet WCAG AA contrast for body text and for the accent colour against the paper background.   <!-- eval: frontend-shell-021 -->
22. THE SYSTEM SHALL NOT initialize or send any product-analytics (PostHog) event from the frontend.   <!-- eval: frontend-shell-022 -->

## Non-functional / contract

- **Contract fields READ** (rendered, never computed by the frontend): `reply`, `active_lang`,
  `detected_lang`, `needs_review`, `guardrails.input`, `guardrails.output`, and — only behind the
  `details_disclosure` flag — `lang_confidence`, `confidence_score`, `final_normalized_text`,
  `detected_country`.
- **Contract fields WRITTEN**: none. The frontend sends only `session_id` and the student `message`.
- **Languages**: the UI supports **ES, EN, PT** at runtime, mirroring `active_lang`; an `active_lang`
  outside that set falls back to `en` chrome (criterion 16). The backend already guarantees
  `active_lang ∈ {es, en, pt}` (see `multilingual`); criterion 16 is the defensive UI fallback.
- **Privacy**: no analytics SDK in the frontend; student message content and any PII stay server-side
  (Logfire/backend) per the stakeholder decision.
- **Performance/UX**: full-reply render on response (no token streaming in this feature).

## Case-id map

Each acceptance line `frontend-shell-001 … frontend-shell-022` maps **1:1** to a frontend component
test of the same id (Vitest + @testing-library/react), carried inline as `<!-- eval: frontend-shell-NNN -->`.
Rationale: the `pydantic-evals` harness covers backend/runtime contract behavior, not browser
rendering, so this feature's "eval Cases" are realized as deterministic component tests that assert
the rendered DOM/behavior for one criterion each. No orphans in either direction: every criterion
has exactly one test id and vice versa. Numbering is append-only — never renumber on revision.
