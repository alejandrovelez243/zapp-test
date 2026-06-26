# Frontend Shell Design

## Architecture overview

`frontend-shell` is the Next.js App Router application (deployed on Vercel) at the head of the
runtime path:

```
Browser ── Next.js (RSC shell + client chat island)
        └─ Next rewrite /api/* ──▶ FastAPI /chat (Railway)
                                     └─▶ PydanticAI orchestrator (agent-as-tool)
                                          ├─▶ FAQ-RAG agent (pgvector)
                                          └─▶ EVENTS agent (.ics)
```

The frontend is a **read-only consumer** of the per-turn JSON contract. It sends only
`{ session_id, message }` and renders the returned `TurnOutput`. It never computes a contract field;
the orchestrator + `multilingual` / `guardrails` / `orchestrator-and-fusion` own those.

**Observability.** Logfire tracing attaches **in the backend only** (one distributed trace per
turn). **No PostHog / product-analytics SDK is loaded in the frontend** (stakeholder decision —
supersedes the PostHog mandate in `frontend/CLAUDE.md`, to be corrected separately). Any product
analytics is backend-side. This keeps student message content + PII server-side (Logfire), satisfying
criterion `frontend-shell-022`.

**Rendering strategy.** Server Components by default; a single Client island (`ChatShell`) holds the
interactive transcript/composer state. Styling is Tailwind + shadcn/ui primitives over a classical
design-token theme. i18n is a lightweight runtime dictionary keyed by `active_lang` (no URL locale
routing — language is session-locked by the backend).

## Module & component structure

```
frontend/
  next.config.ts                 # rewrite /api/:path* -> ${NEXT_PUBLIC_API_URL}/:path*  (proxy, no CORS)
  tailwind.config.ts             # classical theme tokens (palette, type scale, fonts)
  postcss.config.mjs
  components.json                # shadcn/ui config
  vitest.config.ts               # jsdom + @testing-library
  app/
    layout.tsx        (RSC)      # next/font (serif display + humanist sans + mono), metadata, theme; NO analytics
    page.tsx          (RSC)      # renders <ChatShell/>
    globals.css                  # Tailwind layers + CSS-var tokens + meander hairline util + reduced-motion
  lib/
    contract.ts                  # TurnOutput TS type (the 9 contract fields) + ChatTurn view model
    api.ts                       # postTurn(session_id, message) -> TurnOutput | ApiError
    session.ts                   # anonymous session_id (crypto.randomUUID, sessionStorage)
    i18n/{index.ts,es.ts,en.ts,pt.ts}   # t(active_lang, key); fallback 'en'
    hooks/useChat.ts             # state machine: idle -> sending -> rendered | error
    flags.ts                     # details_disclosure = NEXT_PUBLIC_SHOW_DETAILS === '1'
  components/
    chat/ChatShell.tsx ("use client")   # owns transcript + session, calls useChat
    chat/Transcript.tsx                  # aria-live region; lists MessageTurn
    chat/MessageTurn.tsx                 # one turn; renders reply + ContractMeta
    chat/Composer.tsx                    # textarea; Enter submits, Shift+Enter newline
    chat/contract/LangIndicator.tsx      # discreet active_lang
    chat/contract/DetectedLangHint.tsx   # quiet "session locked" hint when detected_lang != active_lang
    chat/contract/ReviewMarker.tsx       # hairline side-rule + tooltip for needs_review
    chat/contract/GuardrailNote.tsx      # calm "filtered" affordance when guardrails non-empty
    chat/contract/DetailsDisclosure.tsx  # flag-gated <Collapsible> of debug fields
    ui/*                                  # shadcn primitives: button, textarea, tooltip, collapsible, badge
```

## Component contracts

- **`lib/api.ts` `postTurn(sessionId, message)`** — POST `/api/chat` (proxied to FastAPI `/chat`)
  with body `{ session_id, message }`. Returns the parsed `TurnOutput` on 2xx; on network failure or
  a body that fails `TurnOutput` shape validation, returns a typed `ApiError` (never throws to the
  view). Satisfies `frontend-shell-003/004/006`.
- **`lib/contract.ts` `TurnOutput`** — TS mirror of the canonical contract (read-only):
  `reply: string`, `detected_lang: string`, `active_lang: 'es'|'en'|'pt'|string`,
  `lang_confidence: number`, `final_normalized_text: string`, `detected_country: string`,
  `confidence_score: number`, `needs_review: boolean`,
  `guardrails: { input: string[]; output: string[] }`. A runtime guard (`isTurnOutput`) validates
  inbound JSON so criterion 6 (non-contract response → error) is enforceable.
- **`lib/session.ts`** — returns a stable per-tab `session_id` (`crypto.randomUUID()`, cached in
  `sessionStorage`), sent on every turn (`frontend-shell-002`).
- **`lib/i18n`** — `t(active_lang, key, vars?)` resolves chrome copy from `es|en|pt` dicts; an
  `active_lang` outside the set falls back to `en` (`frontend-shell-014/015/016`).
- **`hooks/useChat.ts`** — append-user-turn → `sending` (pending indicator, submit disabled) →
  on result append assistant turn / on error append error affordance, transcript preserved
  (`frontend-shell-003/005/006`).
- **`ContractMeta` family** — pure presentational components reading one `TurnOutput`; render
  `needs_review`, `active_lang`, `detected_lang` mismatch, `guardrails`, and (flag-gated) the four
  debug fields. No raw guardrail internals leak (`frontend-shell-008..013`).

## Data models

```ts
// lib/contract.ts
export interface TurnOutput {
  reply: string;
  detected_lang: string;
  active_lang: string;            // backend guarantees es|en|pt; UI defends with en fallback
  lang_confidence: number;
  final_normalized_text: string;
  detected_country: string;
  confidence_score: number;
  needs_review: boolean;
  guardrails: { input: string[]; output: string[] };
}
export type ChatTurn =
  | { role: 'student'; text: string }
  | { role: 'assistant'; text: string; contract: TurnOutput }
  | { role: 'error'; text: string };

// lib/i18n
export type Lang = 'es' | 'en' | 'pt';
export type Dict = Record<I18nKey, string>;   // I18nKey: 'composer.placeholder' | 'send' | 'thinking' | 'error.generic' | 'lang.locked' | 'filtered' | 'details.toggle' | ...
```

No SQLModel / pgvector / `.ics` shapes — this feature touches no DB and no events surface.

### Design tokens (theme)

- **Palette (one accent):** paper/ivory `--paper: #F4EFE6`, ink `--ink: #1A1714`, muted greys for
  hairlines, and a **single accent** `--accent: deep aubergine #6E2C50` (links/active/focus). Chosen
  over terracotta ochre for WCAG-AA text contrast on ivory (`frontend-shell-021`). Decorative
  Greek-key hairlines use ink at low opacity, not the accent, preserving the one-accent rule.
- **Type:** display serif (**Newsreader**) for headings; quiet humanist sans (**Public Sans**) for
  UI/labels; mono (**JetBrains Mono**) for tokens/ids — all via `next/font/google`. Modular scale;
  reading measure ~66ch.
- **Meander util:** a `.rule-meander` hairline (CSS repeating-gradient or inline SVG) for section
  rules — the classical nod, kept subtle (`frontend-shell-017`).
- **Motion:** 150–250ms fade/translate on turn append; fully disabled under
  `@media (prefers-reduced-motion: reduce)` (`frontend-shell-018`).

## Sequence diagrams

### Happy path

```mermaid
sequenceDiagram
  actor S as Student
  participant UI as ChatShell (client)
  participant PX as Next /api proxy
  participant BE as FastAPI /chat
  participant OR as Orchestrator
  S->>UI: type message, press Enter
  UI->>UI: append student turn; state=sending (pending, submit disabled)
  UI->>PX: POST /api/chat {session_id, message}
  PX->>BE: POST /chat
  BE->>OR: run(message, session)
  OR-->>BE: TurnOutput (9 fields)
  BE-->>PX: 200 TurnOutput
  PX-->>UI: 200 TurnOutput
  UI->>UI: validate shape; append assistant turn (reply)
  UI->>S: render reply + discreet active_lang (aria-live announces)
```

### Degraded path (low confidence / guardrail / unsupported lang / failure)

```mermaid
sequenceDiagram
  actor S as Student
  participant UI as ChatShell (client)
  participant PX as Next /api proxy
  participant BE as FastAPI /chat
  S->>UI: submit message
  UI->>PX: POST /api/chat
  alt backend returns contract with needs_review / guardrails / fallback active_lang
    PX-->>UI: 200 TurnOutput (needs_review=true OR guardrails non-empty)
    UI->>UI: render reply + quiet hairline ReviewMarker (no red banner)
    UI->>UI: if guardrails non-empty -> calm "filtered" note (no internals)
    UI->>UI: if active_lang unsupported -> chrome falls back to en
    UI->>S: informed, not alarmed
  else network/5xx/non-contract body
    PX-->>UI: error / malformed
    UI->>UI: append localized error affordance; transcript preserved
    UI->>S: localized error in active_lang (or en fallback)
  end
```

## Traceability

| Requirement | Component(s) |
|---|---|
| frontend-shell-001 | `ChatShell`, `Transcript`, `Composer` |
| frontend-shell-002 | `lib/session.ts`, `useChat` |
| frontend-shell-003 | `Composer`, `useChat`, `lib/api.ts` |
| frontend-shell-004 | `useChat`, `MessageTurn` |
| frontend-shell-005 | `useChat` (sending state), `Composer` (disabled) |
| frontend-shell-006 | `lib/api.ts` (ApiError), `useChat`, `MessageTurn` (error) |
| frontend-shell-007 | `Composer` (Enter / Shift+Enter handler) |
| frontend-shell-008 | `contract/ReviewMarker.tsx` |
| frontend-shell-009 | `contract/LangIndicator.tsx` |
| frontend-shell-010 | `contract/DetectedLangHint.tsx` |
| frontend-shell-011 | `contract/GuardrailNote.tsx` |
| frontend-shell-012 | `contract/DetailsDisclosure.tsx`, `lib/flags.ts` |
| frontend-shell-013 | `contract/DetailsDisclosure.tsx`, `lib/flags.ts` |
| frontend-shell-014 | `lib/i18n`, all chrome components |
| frontend-shell-015 | `lib/i18n`, `ChatShell` (re-renders on active_lang change) |
| frontend-shell-016 | `lib/i18n` (en fallback) |
| frontend-shell-017 | `tailwind.config.ts`, `globals.css` (`.rule-meander`), `layout.tsx` fonts |
| frontend-shell-018 | `globals.css` (reduced-motion) |
| frontend-shell-019 | `Transcript` (aria-live) |
| frontend-shell-020 | `Composer`, `DetailsDisclosure`, focus-ring tokens |
| frontend-shell-021 | theme tokens (palette contrast) |
| frontend-shell-022 | absence of any analytics module; `layout.tsx` loads no SDK |

## Open Decisions / Rejected Alternatives

- **PostHog excluded from the frontend (chosen).** Stakeholder decision: analytics is backend-only.
  This **supersedes `frontend/CLAUDE.md`'s** PostHog/`instrumentation-client.ts` mandate — that rule
  file should be corrected in a follow-up. *Revisit if* product needs a client-side conversion funnel
  that the backend cannot reconstruct.
- **i18n via runtime dictionary (chosen)** vs `next-intl` / URL-locale routing (**rejected**): the
  backend locks session language (`active_lang`); there is no locale in the URL and no SEO surface to
  justify routing. *Revisit if* public, indexable localized pages are added.
- **Full-reply render now (chosen)** vs token-by-token streaming (**deferred**): backend `/chat`
  returns a complete JSON body (no SSE). True streaming needs a backend SSE endpoint (separate
  feature). *Revisit when* the backend exposes a streaming `/chat`.
- **shadcn/ui primitives (chosen)** vs hand-rolled components (**rejected**): accessible
  tooltip/collapsible/focus behavior is costly to re-implement correctly.
- **Single accent = deep aubergine (chosen)** vs terracotta ochre (**rejected for text**): ochre
  fails AA on ivory for body/links; retained only conceptually as a decorative tint if ever needed.
- **Details disclosure gated by `NEXT_PUBLIC_SHOW_DETAILS` (chosen)** vs admin-token gate
  (**deferred**): admin auth belongs to the later admin feature; a build-time flag is enough now.
- **Server shell + single client island (chosen)** vs fully client app (**rejected**): keeps the
  static shell server-rendered, isolates interactivity.
- **Backend canon (recorded, N/A to this feature):** **ADK-rejected** — PydanticAI is the only
  in-process runtime (ADK would only compose via A2A HTTP); **PageIndex-deferred** — RAG stays
  pgvector/HNSW. The frontend neither selects a runtime nor a retriever, so these constrain only the
  backend it talks to.
