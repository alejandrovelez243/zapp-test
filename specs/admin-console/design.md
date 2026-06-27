# Admin Console Design

## Architecture overview

`admin-console` is a **frontend-only** feature on the Next.js App Router app (Vercel). Runtime path:

```
Admin browser ── /admin (RSC shell) + <AdminConsole/> (client island)
              └─ Next rewrite /api/* ──▶ FastAPI /documents (Railway)   [owned by faq-rag]
                                          POST(upload) · GET(list) · PUT(replace) · DELETE
```

It is a pure **consumer** of the existing `/documents` REST API — **no backend change**, no agents,
no tools, no per-turn `TurnOutput` contract. The admin token is held client-side and sent as the
`X-Admin-Token` header on every request.

**Observability.** Logfire tracing attaches **backend-side** on the `/documents` routes; the frontend
loads **no analytics SDK** (consistent with `frontend-no-posthog`). PostHog is backend-only.

**Rendering.** `app/admin/page.tsx` stays an RSC shell (editorial header + `.rule-meander`); all
interactivity lives in the single client island `AdminConsole`. English-only copy (no i18n dict).

## Design plan (frontend-design)

Brief pins the visual direction: **reuse the established classical system** (the chat already uses
it; consistency wins, and the skill says the brief wins). We do not introduce a new identity.

- **Color** (existing tokens, `globals.css`): paper `#F4EFE6`, ink `#1A1714`, single accent aubergine
  `#6E2C50` (actions/links/focus `--ring`), warm-grey hairlines `--border #C4BDB1`,
  `--muted-foreground #6B6259`. Status uses tone, not new hues: ready = accent/ink, pending/ingesting
  = muted grey + motion, failed = the muted terracotta `--destructive` at low emphasis (a quiet mark,
  never an alarm banner — req admin-console-015).
- **Type** (existing): Newsreader (serif) headings, Public Sans (UI/body), JetBrains Mono (ids,
  filenames, status text).
- **Signature**: the **upload dropzone** is the one memorable element — a generous, quiet drop target
  bordered with a `.rule-meander`-derived hairline that intensifies (accent) on drag-over; it is the
  hero of the console and the most direct expression of "make corpus upkeep effortless."
- **Layout**: single centered column (~72ch) matching the chat shell; dropzone on top, document list
  below as cards (not a raw `<table>`), each card a row: filename (mono) · status pill · actions.
- **Motion**: calm — drag-over border transition, card enter/exit fade, pill state cross-fade; all
  disabled under `prefers-reduced-motion`.

## Component & module structure

This **refactors** the current monolithic `components/admin/DocumentsManager.tsx` (776 LOC, raw file
input + HTML table) into focused, testable components:

```
app/admin/page.tsx            (RSC) editorial shell -> <AdminConsole/>
components/admin/
  AdminConsole.tsx            ("use client") root state machine: token gate vs console; mounts Toaster
  TokenGate.tsx               token-entry form (password input, Continue); error message slot
  UploadDropzone.tsx          drag/drop + click + keyboard file select; .pdf/.md/.txt validation
  DocumentList.tsx            cards list; empty state; manual Refresh; drives auto-poll
  DocumentCard.tsx            one doc: filename + <StatusPill> + Replace/Delete actions
  StatusPill.tsx              pending|ingesting|ready|failed -> token-styled pill (failed = calm)
  DeleteConfirm.tsx           modal confirm (shadcn dialog) before DELETE
  Toaster.tsx                 aria-live toast region + useToast() (lightweight, in-house)
components/ui/                + add shadcn primitives: dialog (alert), card, progress (see Open Decisions)
lib/
  adminApi.ts                 EXISTS — list/upload/delete/replace + AdminApiError union (reuse as-is)
  hooks/useDocuments.ts       (new) token + list + polling + upload/replace/delete + toast wiring
```

## Component contracts

- **`lib/adminApi.ts`** (existing, reused): `listDocuments(token)` → `DocumentSummary[] | AdminApiError`;
  `uploadDocument(token, file)` / `replaceDocument(token, id, file)` → `{id} | AdminApiError`;
  `deleteDocument(token, id)` → `true | AdminApiError`; `isAdminApiError()`. Error kinds:
  `auth(401/403) | notfound(404) | invalid(422) | http | network | malformed`. Calls go to
  same-origin `/api/documents*` (Next rewrite → FastAPI).
- **`useDocuments(token)`** (new hook): owns `{ docs, listError, isLoading, upload(file), replace(id,file),
  remove(id), refresh() }` plus a status-poll effect. On `auth` error from any call it raises a
  sign-out signal consumed by `AdminConsole` (clears token → `TokenGate`). req: admin-console-002,003,
  008–013,016,017.
- **`UploadDropzone`**: props `{ onFile(file), disabled }`. Validates extension ∈ {pdf,md,txt} before
  emitting; rejects others with an inline message (req 007). Drag, click, and keyboard (Enter/Space on
  the focusable zone opening the file picker) all work (req 006,019).
- **`StatusPill`**: prop `status`; maps to a token-styled pill; `failed` is calm (no red alarm) and
  shows no reason (req 011,015).
- **`Toaster` / `useToast`**: queue of `{id, kind: 'success'|'error', message}` rendered in an
  `aria-live="polite"` region; auto-dismiss (req 009,010,017,020).
- **`DeleteConfirm`**: a focus-trapped modal (shadcn dialog) — confirm sends DELETE, cancel keeps the
  doc and sends nothing (req 017,018).

## Data models (TypeScript)

```ts
type DocStatus = 'pending' | 'ingesting' | 'ready' | 'failed';
interface DocumentSummary { id: number; name: string; status: DocStatus }   // GET /documents item
type AdminApiError =
  | { ok: false; kind: 'auth' | 'notfound' | 'invalid' | 'http' | 'network' | 'malformed';
      status?: number; message: string };
interface Toast { id: string; kind: 'success' | 'error'; message: string }
const ACCEPTED = ['.pdf', '.md', '.txt'] as const;
```

No SQLModel / pgvector / `.ics`/event shapes — backend (`faq-rag`) owns the `Document`/`DocumentChunk`
tables; this feature only reads the `{id,name,status}` projection.

## Sequence diagrams

### Happy path — upload → ingest → ready

```mermaid
sequenceDiagram
  actor A as Admin
  participant UI as AdminConsole (client)
  participant PX as Next /api proxy
  participant BE as FastAPI /documents
  A->>UI: enter token (TokenGate)
  UI->>UI: persist token (sessionStorage); show console
  A->>UI: drag file into UploadDropzone
  UI->>UI: validate ext (.pdf/.md/.txt)
  UI->>PX: POST /api/documents (multipart, X-Admin-Token)
  PX->>BE: POST /documents
  BE-->>UI: 202 {id}
  UI->>A: success toast; refresh list (status=pending)
  loop while any pending/ingesting
    UI->>BE: GET /documents (poll)
    BE-->>UI: [{id,name,status}]
  end
  UI->>A: pill -> ready; polling stops
```

### Degraded paths — bad token / bad file / failed ingest

```mermaid
sequenceDiagram
  actor A as Admin
  participant UI as AdminConsole
  participant BE as FastAPI /documents
  alt invalid/missing token
    UI->>BE: GET /documents (X-Admin-Token)
    BE-->>UI: 401/403
    UI->>UI: clear token -> TokenGate + "token invalid"
  else unsupported file type
    A->>UI: select .docx
    UI->>A: inline reject (no request sent)
  else upload error (422/network)
    UI->>BE: POST /documents
    BE-->>UI: 422 / network fail
    UI->>A: calm error toast; list preserved
  else ingestion fails server-side
    UI->>BE: GET /documents (poll)
    BE-->>UI: status=failed
    UI->>A: calm "failed" pill (no reason, no alarm)
  end
```

## Traceability

| Requirement | Component(s) |
|---|---|
| admin-console-001 | `AdminConsole`, `TokenGate` |
| admin-console-002 | `AdminConsole` (token persist), `lib/adminApi` (X-Admin-Token), `useDocuments` |
| admin-console-003 | `useDocuments` (auth→signout), `AdminConsole`, `TokenGate` |
| admin-console-004 | `AdminConsole` (sign-out control) |
| admin-console-005 | `AdminConsole` (sessionStorage/state only; no NEXT_PUBLIC token) |
| admin-console-006 | `UploadDropzone` (drag + click + keyboard) |
| admin-console-007 | `UploadDropzone` (ext validation) |
| admin-console-008 | `UploadDropzone`, `useDocuments.upload`, `lib/adminApi.uploadDocument` |
| admin-console-009 | `useDocuments`, `Toaster`, `DocumentList` (refresh) |
| admin-console-010 | `useDocuments`, `Toaster` |
| admin-console-011 | `DocumentCard`, `StatusPill` |
| admin-console-012 | `useDocuments` (poll effect) |
| admin-console-013 | `DocumentList` (Refresh) |
| admin-console-014 | `DocumentList` (empty state) |
| admin-console-015 | `StatusPill` (failed = calm, no reason) |
| admin-console-016 | `DocumentCard`, `useDocuments.replace`, `UploadDropzone` (reuse) |
| admin-console-017 | `DeleteConfirm`, `useDocuments.remove`, `Toaster` |
| admin-console-018 | `DeleteConfirm` (cancel path) |
| admin-console-019 | all interactive components + theme `--ring` focus |
| admin-console-020 | `Toaster` (aria-live), `DocumentList` (status announce) |
| admin-console-021 | `globals.css` tokens, all components |
| admin-console-022 | all components (English copy) |

## Open Decisions / Rejected Alternatives

- **Reuse the established classical design system (chosen)** vs a fresh admin identity (**rejected**):
  the brief pins it and the chat already uses it; consistency wins. We expand the system (dropzone,
  cards, pills), not replace it.
- **Refactor the 776-LOC `DocumentsManager` into focused components (chosen)** vs patch in place
  (**rejected**): the monolith is untested and hard to test per-criterion; splitting enables the 1:1
  component tests.
- **Lightweight in-house `Toaster` + `aria-live` (chosen)** vs adding `sonner`/a toast dep
  (**rejected**): avoids a dependency and gives full a11y control. *Revisit if* complex
  queueing/stacking is needed.
- **shadcn `dialog` (alert) for delete confirm (chosen)** vs an inline two-step button (**rejected**):
  a focus-trapped modal is the accessible pattern for a destructive confirm; add the primitive via the
  shadcn CLI (also evaluate `card`/`progress` primitives for the list/upload — add only if they pull
  their weight; a plain styled element is fine otherwise).
- **Client polling of `GET /documents` while pending/ingesting, stop when settled (chosen)** vs
  WebSocket/SSE push (**rejected**): the backend updates status in the DB with no push channel;
  polling is the intended pattern (and matches `faq-rag` design). Use a bounded interval; stop when no
  doc is in-flight.
- **Failure reason not surfaced (chosen, stakeholder)**: backend `error` exists but is not in the
  `DocumentSummary` projection; the UI shows `failed` only. *Revisit if* the team needs the reason
  (would be a small `faq-rag` backend change to expose `error`).
- **English-only console (chosen)**: internal staff tool; no i18n dict. The public chat stays ES/EN/PT.
- **No analytics in the frontend** (consistent with `frontend-no-posthog`).
- **Backend canon (recorded, N/A here)**: **ADK-rejected** (PydanticAI is the only in-process runtime;
  ADK would compose only via A2A HTTP) and **PageIndex-deferred** (RAG stays pgvector/HNSW). This
  feature neither selects a runtime nor a retriever — it manages documents over the existing API.
