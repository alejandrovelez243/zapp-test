# frontend/ — Next.js (App Router) on Vercel

Path-scoped rules for the web client: a chat UI for the Philosophy School and an
admin surface for document/event management. Only write code here when `/implement`
is running and a spec trio is already committed; the `require-spec` hook (active once
registered — see `.claude/hooks/README.md`) blocks `backend/`/`frontend/` commits until
at least one committed spec trio exists in `HEAD`.

## Stack

Next.js **App Router**, TypeScript, deployed on **Vercel**. UI built with **shadcn/ui**
+ Tailwind. The product is multilingual (**ES / EN / PT**, fallback for unsupported);
mirror `active_lang` from the per-turn contract in the UI.

- **Package manager: `pnpm`.** Add/remove deps ONLY via `pnpm add <pkg>` / `pnpm add -D <pkg>` /
  `pnpm remove`. **NEVER hand-edit** `package.json` deps or `pnpm-lock.yaml`. Scripts:
  `pnpm install` / `pnpm dev` / `pnpm build` / `pnpm lint`. Commit `pnpm-lock.yaml`;
  CI/images install with `pnpm install --frozen-lockfile` (enable via `corepack`).
- Runs locally under **Docker Compose** as an optional service, or directly with `pnpm dev`.

## Talking to the backend

- Call the FastAPI backend via **`NEXT_PUBLIC_API_URL`**. Render every per-turn
  contract field the UX needs (`reply`, `active_lang`, `needs_review`, `guardrails`,
  `confidence_score`) — surface `needs_review=true` states gracefully to the user.
- **CORS is handled server-side**: prefer **Next.js rewrites** to proxy `/api/*` to the
  backend (no CORS at all). If calling cross-origin instead, the backend allows the
  exact Vercel prod domain plus `allow_origin_regex r'https://.*\.vercel\.app'` for
  changing preview URLs. Do not add ad-hoc CORS workarounds in the client.

## Environment variables

- **`NEXT_PUBLIC_*` are build-time inlined** into the bundle — they are **NEVER secrets**.
  Changing one requires a **redeploy** to take effect. Keep all real secrets server-side
  (Route Handlers / Server Actions), never in `NEXT_PUBLIC_*`.
- Vercel **Root Directory = `frontend/`**.

## Analytics — NONE in the frontend (PostHog is backend-only)

- **The frontend wires NO product-analytics SDK.** Do NOT add `posthog-js`,
  `instrumentation-client.ts`, a `/ingest` reverse-proxy rewrite, or any tracking
  script. There is no client-side PostHog.
- **All product analytics lives on the backend.** PostHog is initialized and sent
  server-side only; student message content and PII never leave the server (content
  tracing is Logfire on the backend). This keeps the client free of any SDK that could
  leak message content or PII.
- Tier-3 risky-feature toggles are driven by **backend config / env flags** (e.g.
  `NEXT_PUBLIC_SHOW_DETAILS` for the build-time debug disclosure), not a client PostHog
  feature-flag SDK.
- Enforced by `specs/frontend-shell` (criterion `frontend-shell-022` + a component
  test asserting no analytics is initialized from the frontend).

## Visual character

Aim for a distinctive, intentional **philosophical** aesthetic — classical, considered,
typographically rich; not a templated default dashboard. Use the `frontend-design` and
`shadcn` skills for direction. Keep it accessible and responsive.

## Code quality

TypeScript strict; Server Components by default, Client Components only where needed;
colocate components; keep data-fetching on the server. Lint/format clean before commit.
