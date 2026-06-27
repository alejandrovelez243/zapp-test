# Admin Console Requirements

## Summary

The school team needs to keep the FAQ-RAG document corpus current without touching curl or the
database. `admin-console` is the **frontend** document-management console at `/admin`: a modern,
intuitive surface to upload, list, replace, and delete the documents that ground FAQ answers, with
clear ingestion-status feedback. It is a token-gated **internal staff tool** — English-only — and a
pure consumer of the existing `/documents` REST API (owned by the `faq-rag` feature). It does not
touch the per-turn chat contract. An admin console already exists ad-hoc (a raw file input + an HTML
table); this feature replaces it with a polished, accessible design built within the project's
established classical design system.

## In / Out of scope

In scope: the `/admin` console UI — client-side admin-token gate (entry form + sign-out), a
drag-and-drop upload zone with keyboard/click fallback (PDF/MD/TXT), document cards/rows with a
status pill (pending / ingesting / ready / failed), auto-polling of status while work is in flight,
empty state, replace (re-upload) and delete with explicit confirmation, calm toast feedback, full
keyboard a11y (WCAG AA), and component tests. Reuses the established design tokens (ivory/ink +
single aubergine accent, serif headings, `.rule-meander`).

Out of scope: any backend change (consumes the existing `faq-rag` `/documents` API as-is); exposing
the ingestion **failure reason** (the backend `error` field is not surfaced — failed status is shown
without a reason); **events** management UI; admin-console **i18n** (English-only); the per-turn
`TurnOutput` contract (not read or written here); product analytics (none — see
`frontend-no-posthog`).

## Config flags & config values

- No feature flags. Config values: `api_base` (`NEXT_PUBLIC_API_URL`, proxied via the existing Next
  `/api/*` rewrite — never a secret). The admin token is entered at runtime, never a build-time var.

## User Stories

- As a school-team admin, I want to drag a document in and see it ingest, so that keeping the FAQ
  corpus current is effortless and obvious.
- As an admin, I want each document's status shown clearly (and updated on its own while ingestion
  runs), so that I know when it is live without manual refreshing.
- As an admin, I want to replace or delete a document with a clear confirmation, so that I don't
  destroy the corpus by accident.
- As an admin, I want the console gated behind my token and to sign out, so that management stays
  protected on a shared machine.
- As a keyboard or screen-reader user on the team, I want full operability and announced status, so
  that the console is usable without a mouse.

## Acceptance Criteria

1. WHILE no valid admin token is held THE SYSTEM SHALL show a token-entry form AND SHALL NOT call any document-management endpoint.   <!-- eval: admin-console-001 -->
2. WHEN the admin submits a token THE SYSTEM SHALL persist it for the browser session and send it as the `X-Admin-Token` header on every document request.   <!-- eval: admin-console-002 -->
3. IF a document request returns 401 or 403 THEN THE SYSTEM SHALL clear the stored token, return to the token-entry form, AND show that the token is missing or invalid.   <!-- eval: admin-console-003 -->
4. THE SYSTEM SHALL provide a sign-out control that clears the stored token and returns to the token-entry form.   <!-- eval: admin-console-004 -->
5. THE SYSTEM SHALL NOT place the admin token in a build-time/public env var or the page bundle (token lives only in session state/storage).   <!-- eval: admin-console-005 -->
6. THE SYSTEM SHALL provide a drag-and-drop upload zone that ALSO supports selection by keyboard and a file picker (click).   <!-- eval: admin-console-006 -->
7. WHEN the admin drops or selects a file THE SYSTEM SHALL accept only `.pdf`, `.md`, or `.txt` AND reject other types with a clear message before any upload request.   <!-- eval: admin-console-007 -->
8. WHEN the admin confirms an upload THE SYSTEM SHALL POST the file as multipart to the documents endpoint with the admin token AND show pending/in-progress feedback.   <!-- eval: admin-console-008 -->
9. WHEN an upload succeeds THE SYSTEM SHALL show a success toast AND refresh the document list.   <!-- eval: admin-console-009 -->
10. IF an upload fails (invalid type, network, or server error) THEN THE SYSTEM SHALL show a calm error toast explaining what happened AND preserve the current list.   <!-- eval: admin-console-010 -->
11. THE SYSTEM SHALL display each document as a card/row showing its name and a status pill (pending, ingesting, ready, or failed) using the design-system tokens.   <!-- eval: admin-console-011 -->
12. WHILE any document is `pending` or `ingesting` THE SYSTEM SHALL poll the list endpoint periodically AND stop polling once every document is `ready` or `failed`.   <!-- eval: admin-console-012 -->
13. THE SYSTEM SHALL provide a manual refresh control for the document list.   <!-- eval: admin-console-013 -->
14. WHEN there are no documents THE SYSTEM SHALL show an empty state that invites the admin to upload the first document.   <!-- eval: admin-console-014 -->
15. WHERE a document's status is `failed` THE SYSTEM SHALL render that state distinctly and calmly (no red alarm banner) AND SHALL NOT expose internal error details.   <!-- eval: admin-console-015 -->
16. WHEN the admin replaces a document THE SYSTEM SHALL PUT the new file as multipart to that document's endpoint, show feedback, AND refresh the list.   <!-- eval: admin-console-016 -->
17. WHEN the admin requests deletion THE SYSTEM SHALL require an explicit confirmation before sending the DELETE, AND on success remove the document from the list with a toast.   <!-- eval: admin-console-017 -->
18. IF the admin cancels the delete confirmation THEN THE SYSTEM SHALL NOT send the request AND SHALL keep the document.   <!-- eval: admin-console-018 -->
19. THE SYSTEM SHALL be fully keyboard operable (token form, upload zone, refresh, replace, delete, confirm) with a visible focus indicator on every interactive element.   <!-- eval: admin-console-019 -->
20. THE SYSTEM SHALL announce status changes and toast messages to assistive technology via an `aria-live` region.   <!-- eval: admin-console-020 -->
21. THE SYSTEM SHALL render the console in the established classical design system (ivory/ink palette, single aubergine accent, serif headings, `.rule-meander`) AND meet WCAG AA contrast.   <!-- eval: admin-console-021 -->
22. THE SYSTEM SHALL present all console copy in English.   <!-- eval: admin-console-022 -->

## Non-functional / contract

- **Per-turn JSON contract**: NOT read or written by this feature. `admin-console` manages documents
  exclusively through the `/documents` REST API (`POST` upload, `GET` list → `{id, name, status}`,
  `DELETE`, `PUT` replace) defined by `faq-rag`. No `reply`/`active_lang`/`needs_review`/`guardrails`.
- **Languages**: the console UI is **English-only** (internal staff tool); it does not use
  `active_lang`. The public chat remains ES/EN/PT (`frontend-shell`).
- **Auth**: client-side `X-Admin-Token` header, entered at runtime and held only in session
  state/storage — never in `NEXT_PUBLIC_*` or the bundle.
- **Privacy**: no analytics SDK in the frontend (consistent with `frontend-no-posthog`).
- **Status model**: document status ∈ {`pending`, `ingesting`, `ready`, `failed`}; the failure
  reason is intentionally not surfaced (backend `error` field is not exposed in this release).

## Case-id map

Each acceptance line `admin-console-001 … admin-console-022` maps **1:1** to a frontend component
test of the same id (Vitest + @testing-library/react), carried inline as
`<!-- eval: admin-console-NNN -->`. Rationale (as for `frontend-shell`): the `pydantic-evals` harness
covers backend/runtime behavior, not browser rendering, so this UI feature's "eval Cases" are
realized as deterministic component tests, one per criterion. No orphans in either direction;
numbering is append-only.
