# Philosophy School — Chat Shell

Frontend for the Zapp Philosophy School platform. A streaming conversational chat surface built with Next.js (App Router), Tailwind v4, and shadcn/ui, deployed on Vercel.

## What it does

- Renders a single-column chat interface where students submit questions in ES, EN, or PT and receive streamed answers from the backend AI agent.
- Mirrors `active_lang` from the per-turn contract in all UI chrome; shows a quiet hint when the session is locked to a fallback language.
- Surfaces `needs_review` turns with a discreet hairline side-rule and accessible tooltip — never a red banner.
- Shows guardrail-triggered turns with a calm "filtered" affordance; hides raw guardrail internals.
- Exposes `lang_confidence`, `confidence_score`, `final_normalized_text`, and `detected_country` only in a flag-gated collapsible (admin/debug); the conversational surface stays clean.
- Persists an anonymous `session_id` in `sessionStorage` and sends it on every turn for multi-turn memory.
- Proxies all `/api/*` requests through a Next.js rewrite to `NEXT_PUBLIC_API_URL` so the browser makes same-origin calls (no CORS).

## Visual character

Typography-forward, near-monochrome, deliberately editorial. Newsreader serif for headings and assistant voice; Public Sans humanist sans for UI labels; JetBrains Mono for tokens/ids. Warm ivory background, near-black ink text, single aubergine accent (`--accent`). Generous whitespace, narrow readable measure (~66 ch). No gradients, no heavy shadows, no card-everything. Honors `prefers-reduced-motion`.

## Supported languages

ES (Spanish), EN (English), PT (Portuguese). Unsupported language input locks `active_lang` to the configured fallback and sets `needs_review=true`; the UI degrades gracefully with a quiet notice.

## Scripts

```bash
pnpm dev          # local dev server (http://localhost:3000)
pnpm build        # production build (runs Next.js compiler)
pnpm lint         # ESLint
pnpm typecheck    # tsc --noEmit
pnpm test         # Vitest component tests (jsdom)
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Yes | Base URL of the FastAPI backend (e.g. `https://api.example.com`). Build-time inlined — redeploy to change. |
| `NEXT_PUBLIC_SHOW_DETAILS` | No | Set to `true` to enable the per-turn contract details disclosure for admins/debug. Defaults to off. |

Copy `.env.local.example` to `.env.local` and fill in the values before running locally.

> **Note:** `NEXT_PUBLIC_*` variables are never secrets — they are inlined into the browser bundle at build time. Never put admin tokens or API keys in them.

## Per-turn contract

The backend streams and then emits this canonical JSON on every turn. The frontend renders from it:

```json
{
  "reply": "string",
  "detected_lang": "es",
  "active_lang": "es",
  "lang_confidence": 0.97,
  "final_normalized_text": "string",
  "detected_country": "MX",
  "confidence_score": 0.0,
  "needs_review": false,
  "guardrails": { "input": [], "output": [] }
}
```

## Architecture

```
app/
  layout.tsx          RSC — fonts, metadata, theme
  page.tsx            RSC — mounts <ChatShell />
  globals.css         Tailwind layers, CSS-var design tokens, Greek-key hairline
components/
  chat/
    ChatShell.tsx     Client island — useChat state machine, Transcript, Composer
    Transcript.tsx    aria-live scrolling turn list
    MessageTurn.tsx   Single turn with ContractMeta annotations
    Composer.tsx      Textarea, Enter-to-send, Shift+Enter newline, pending state
  contract/
    LangIndicator.tsx         Discreet active_lang badge
    DetectedLangHint.tsx      Quiet locked-language hint on mismatch
    ReviewMarker.tsx          Hairline side-rule + tooltip for needs_review
    GuardrailNote.tsx         Calm "filtered" affordance
    DetailsDisclosure.tsx     Flag-gated collapsible of debug contract fields
lib/
  contract.ts   TurnOutput type + isTurnOutput guard + ChatTurn view model
  api.ts        postTurn → TurnOutput | ApiError (never throws to the view)
  session.ts    Anonymous session_id via crypto.randomUUID, sessionStorage-persisted
  i18n/         ES/EN/PT chrome dictionaries + t() resolver
  flags.ts      details_disclosure flag from NEXT_PUBLIC_SHOW_DETAILS
```

## Deployment

Vercel Root Directory is `frontend/`. Set environment variables in the Vercel project settings. CI runs `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` on every push.
