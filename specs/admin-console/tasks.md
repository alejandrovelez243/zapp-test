# Admin Console Tasks

Ordered, dependency-aware. Primitives → hook → components → assembly → a11y/motion → tests →
cleanup. All frontend; deps via `pnpm add` only (never hand-edit package.json/lock). Reuse the
existing `lib/adminApi.ts` and the classical design tokens; do NOT change the backend.

- [x] 1. Add the shadcn `dialog` primitive (for the delete confirm) and build an in-house `Toaster` + `useToast()` (an `aria-live="polite"` toast region with auto-dismiss). Evaluate `card`/`progress` primitives — add only if they earn their place. — _req: admin-console-017, admin-console-018, admin-console-020 — owner: frontend-engineer_
- [x] 2. Implement `lib/hooks/useDocuments.ts`: owns `{docs, listError, isLoading, upload, replace, remove, refresh}`, a status-poll effect (poll `GET /documents` while any doc is `pending`/`ingesting`, stop when all `ready`/`failed`), and an auth→sign-out signal; wires success/error toasts. Reuses `lib/adminApi.ts`. — _req: admin-console-002, admin-console-003, admin-console-008, admin-console-009, admin-console-010, admin-console-012, admin-console-013, admin-console-016, admin-console-017 — owner: frontend-engineer_
- [x] 3. `components/admin/TokenGate.tsx` — token-entry form (password input + Continue) with an error-message slot; English copy. — _req: admin-console-001, admin-console-003, admin-console-019, admin-console-022 — owner: frontend-engineer_
- [x] 4. `components/admin/UploadDropzone.tsx` — drag-and-drop + click + keyboard (Enter/Space) file select; accept only `.pdf/.md/.txt` with inline rejection before any request; pending/in-progress feedback. — _req: admin-console-006, admin-console-007, admin-console-008, admin-console-019 — owner: frontend-engineer_
- [ ] 5. `components/admin/StatusPill.tsx` — token-styled pills for `pending`/`ingesting`/`ready`/`failed`; `failed` is calm (no red alarm, no reason). — _req: admin-console-011, admin-console-015 — owner: frontend-engineer_
- [ ] 6. `components/admin/DocumentCard.tsx` — one document: filename (mono) + `<StatusPill>` + Replace and Delete actions (Replace reuses the dropzone/file picker). — _req: admin-console-011, admin-console-016, admin-console-019 — owner: frontend-engineer_
- [ ] 7. `components/admin/DeleteConfirm.tsx` — focus-trapped shadcn `dialog`; confirm → DELETE, cancel → send nothing and keep the document. — _req: admin-console-017, admin-console-018, admin-console-019 — owner: frontend-engineer_
- [ ] 8. `components/admin/DocumentList.tsx` — cards list + empty state (invite first upload) + manual Refresh; consumes `useDocuments`; announces status via the aria-live region. — _req: admin-console-011, admin-console-013, admin-console-014, admin-console-020 — owner: frontend-engineer_
- [ ] 9. `components/admin/AdminConsole.tsx` — client root state machine (token gate vs console); persist token in `sessionStorage` (never `NEXT_PUBLIC_*`/bundle); sign-out control; mount `Toaster`; wire `useDocuments`; on auth error return to `TokenGate`. Point `app/admin/page.tsx` at `<AdminConsole/>`. — _req: admin-console-001, admin-console-002, admin-console-003, admin-console-004, admin-console-005 — owner: frontend-engineer_
- [ ] 10. Styling, motion & a11y pass: dropzone drag-over (meander/accent hairline), card enter/exit + pill cross-fade, all gated by `prefers-reduced-motion`; visible `--ring` focus on every control; verify WCAG AA contrast for text + accent on paper. — _req: admin-console-019, admin-console-021 — owner: frontend-engineer_
- [ ] 11. Vitest + @testing-library tests — one per acceptance id `admin-console-001 … -022` (mock `lib/adminApi`), including the negatives: no endpoint call without a token (001/005), no request on invalid file type (007), cancel-delete sends nothing (018), `failed` renders calm with no reason (015), 401/403 → re-gate (003). Carry `// eval: admin-console-NNN`. — _req: admin-console-001 … admin-console-022 (all) — owner: frontend-engineer_
- [ ] 12. Remove the old monolithic `components/admin/DocumentsManager.tsx` once `AdminConsole` replaces it; confirm `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green. — _req: admin-console-021 (cleanup) — owner: frontend-engineer_

## Coverage

| Req | Tasks |
|---|---|
| admin-console-001 | 3, 9, 11 |
| admin-console-002 | 2, 9, 11 |
| admin-console-003 | 2, 3, 9, 11 |
| admin-console-004 | 9, 11 |
| admin-console-005 | 9, 11 |
| admin-console-006 | 4, 11 |
| admin-console-007 | 4, 11 |
| admin-console-008 | 2, 4, 11 |
| admin-console-009 | 1, 2, 11 |
| admin-console-010 | 2, 11 |
| admin-console-011 | 5, 6, 8, 11 |
| admin-console-012 | 2, 11 |
| admin-console-013 | 8, 11 |
| admin-console-014 | 8, 11 |
| admin-console-015 | 5, 11 |
| admin-console-016 | 2, 6, 11 |
| admin-console-017 | 1, 2, 7, 11 |
| admin-console-018 | 7, 11 |
| admin-console-019 | 3, 4, 6, 7, 10, 11 |
| admin-console-020 | 1, 8, 11 |
| admin-console-021 | 10, 11, 12 |
| admin-console-022 | 3, 11 |

12 tasks · owner: **frontend-engineer** (all). Verification is task 11 (one component test per
acceptance id) plus the existing CI frontend gate (typecheck/lint/test/build from `frontend-shell`).
