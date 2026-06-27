# Frontend Shell Tasks

Ordered, dependency-aware. Prerequisites (toolchain, tokens, config, libs) precede consumers
(components, assembly), then tests, then CI. Each task is one specialist delegation / one commit.
Deps are added ONLY via `pnpm add` / `pnpm add -D` — never hand-edit `package.json` or
`pnpm-lock.yaml`.

- [x] 1. Install the styling toolchain via pnpm (Tailwind + PostCSS + autoprefixer), run `shadcn` init, and register the classical font stack (Newsreader / Public Sans / JetBrains Mono) via `next/font/google`. — _req: frontend-shell-017 — owner: frontend-engineer_
- [x] 2. Define design tokens + theme: `tailwind.config.ts` (ivory/ink palette + single aubergine accent, modular type scale, fonts) and `app/globals.css` (Tailwind layers, CSS-var tokens, `.rule-meander` Greek-key hairline, `prefers-reduced-motion` block). Replace the Arial/Georgia scaffold CSS. — _req: frontend-shell-017, frontend-shell-018, frontend-shell-021 — owner: frontend-engineer_
- [x] 3. Wire app config: `next.config.ts` rewrite `/api/:path*` → `${NEXT_PUBLIC_API_URL}/:path*` (proxy, no CORS), `lib/flags.ts` (`details_disclosure` from `NEXT_PUBLIC_SHOW_DETAILS`), and a `.env.local.example`. — _req: frontend-shell-012, frontend-shell-013 — owner: frontend-engineer_
- [x] 4. Implement the contract + transport libs: `lib/contract.ts` (`TurnOutput` type + `isTurnOutput` runtime guard + `ChatTurn` view model), `lib/api.ts` (`postTurn` → `TurnOutput | ApiError`, never throws to the view), `lib/session.ts` (anonymous `session_id` via `crypto.randomUUID`, `sessionStorage`-persisted). — _req: frontend-shell-002, frontend-shell-003, frontend-shell-004, frontend-shell-006 — owner: frontend-engineer_
- [x] 5. Implement i18n: `lib/i18n` with `es`/`en`/`pt` chrome dictionaries, a `t(active_lang, key, vars?)` resolver, and `en` fallback for any non-ES/EN/PT `active_lang`. — _req: frontend-shell-014, frontend-shell-015, frontend-shell-016 — owner: frontend-engineer_
- [ ] 6. Implement the `useChat` hook state machine (idle → sending → rendered | error): appends the student turn, drives the pending state, blocks concurrent submits, appends assistant/error turns preserving the transcript. — _req: frontend-shell-003, frontend-shell-005, frontend-shell-006 — owner: frontend-engineer_
- [ ] 7. Add the shadcn/ui primitives this shell needs (button, textarea, tooltip, collapsible, badge) with the theme tokens applied. — _req: frontend-shell-008, frontend-shell-011, frontend-shell-012, frontend-shell-020 — owner: frontend-engineer_
- [ ] 8. Build `Composer` (textarea; Enter submits, Shift+Enter inserts newline; disabled + pending while a request is in flight; visible focus). — _req: frontend-shell-005, frontend-shell-007, frontend-shell-020 — owner: frontend-engineer_
- [ ] 9. Build `Transcript` + `MessageTurn`: single-column transcript in an `aria-live` region rendering each turn's `reply`. — _req: frontend-shell-001, frontend-shell-004, frontend-shell-019 — owner: frontend-engineer_
- [ ] 10. Build the `ContractMeta` family — `LangIndicator` (discreet `active_lang`), `DetectedLangHint` (quiet locked hint on mismatch), `ReviewMarker` (hairline side-rule + tooltip, no red banner), `GuardrailNote` (calm "filtered", no internals), `DetailsDisclosure` (flag-gated collapsible of `lang_confidence`/`confidence_score`/`final_normalized_text`/`detected_country`; renders nothing when the flag is off). — _req: frontend-shell-008, frontend-shell-009, frontend-shell-010, frontend-shell-011, frontend-shell-012, frontend-shell-013 — owner: frontend-engineer_
- [ ] 11. Assemble `ChatShell` (client island) + `app/page.tsx` (RSC) + `app/layout.tsx` (fonts, metadata replacing "Create Next App", theme); re-render chrome on `active_lang` change; load **no** analytics SDK. — _req: frontend-shell-001, frontend-shell-015, frontend-shell-022 — owner: frontend-engineer_
- [ ] 12. Accessibility pass: full keyboard operability (compose, submit, toggle disclosure), visible focus indicators, WCAG-AA contrast verification of text + accent on paper, reduced-motion honored. — _req: frontend-shell-018, frontend-shell-020, frontend-shell-021 — owner: frontend-engineer_
- [ ] 13. Set up Vitest + `@testing-library/react` + jsdom, add `test` and `typecheck` scripts (pnpm), and write one component test per acceptance id (`frontend-shell-001 … -022`) carrying the `<!-- eval: frontend-shell-NNN -->` id — asserting rendered DOM/behavior for each criterion (incl. the negative cases 013 flag-off and 022 no-analytics). — _req: frontend-shell-001 … frontend-shell-022 (all) — owner: frontend-engineer_
- [ ] 14. Add `typecheck`, `lint`, and `test` steps to the `frontend` job in `.github/workflows/ci.yml` (around the existing `Build frontend` step) so CI runs them frozen and green. — _req: frontend-shell-001 … frontend-shell-022 (CI gate) — owner: devops-engineer_
- [ ] 15. Remove orphaned scaffold (`app/page.module.css`, default `public/*.svg`) and refresh `frontend/README.md` to describe the shell. — _req: frontend-shell-017 — owner: frontend-engineer_

## Coverage

Every requirement id appears in ≥1 task:

| Req | Tasks |
|---|---|
| frontend-shell-001 | 9, 11, 13 |
| frontend-shell-002 | 4, 13 |
| frontend-shell-003 | 3, 4, 6, 8, 13 |
| frontend-shell-004 | 4, 9, 13 |
| frontend-shell-005 | 6, 8, 13 |
| frontend-shell-006 | 4, 6, 13 |
| frontend-shell-007 | 8, 13 |
| frontend-shell-008 | 7, 10, 13 |
| frontend-shell-009 | 10, 13 |
| frontend-shell-010 | 10, 13 |
| frontend-shell-011 | 7, 10, 13 |
| frontend-shell-012 | 3, 7, 10, 13 |
| frontend-shell-013 | 3, 10, 13 |
| frontend-shell-014 | 5, 13 |
| frontend-shell-015 | 5, 11, 13 |
| frontend-shell-016 | 5, 13 |
| frontend-shell-017 | 1, 2, 15 |
| frontend-shell-018 | 2, 12, 13 |
| frontend-shell-019 | 9, 13 |
| frontend-shell-020 | 7, 8, 10, 12, 13 |
| frontend-shell-021 | 2, 12, 13 |
| frontend-shell-022 | 11, 13 |

15 tasks · owners: **frontend-engineer** (1–13, 15), **devops-engineer** (14). Verification is task 13
(component tests, one per acceptance id) + task 14 (CI runs lint/typecheck/test/build).
