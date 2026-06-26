# Frontend image — Next.js + pnpm. (req: platform-scaffold-003, platform-scaffold-019)
#
# Build context is ./frontend. NOTE: the frontend project is scaffolded in Task 15;
# until package.json + pnpm-lock.yaml exist this Dockerfile cannot be built (the
# COPY/install steps have nothing to read). It is authored now so the contract is
# captured in-repo; the first real build happens after Task 15.
#
# Install is ALWAYS `pnpm install --frozen-lockfile` — the committed pnpm-lock.yaml
# is authoritative. NEVER `pnpm add` in the image (that would mutate the lock).

FROM node:22-bookworm-slim

# corepack ships with Node and provisions the pnpm version pinned by the
# "packageManager" field in package.json — no global `npm i -g pnpm` needed.
RUN corepack enable

WORKDIR /app

# --- Dependency layer ---------------------------------------------------------
# Copy manifests first so this layer is cached on manifest changes and survives
# source edits.
#
# pnpm-workspace.yaml MUST be copied alongside package.json + pnpm-lock.yaml:
#   - pnpm 11 hard-errors (ERR_PNPM_IGNORED_BUILDS) on un-approved build scripts
#     in non-interactive mode. The workspace file carries `onlyBuiltDependencies`
#     (sharp, unrs-resolver). Without it pnpm never sees the approval and exits 1.
#   - `"pnpm": {"onlyBuiltDependencies": [...]}` in package.json is the
#     belt-and-suspenders guarantee regardless of workspace resolution order.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# --- Application layer + production build -------------------------------------
COPY . .
RUN pnpm build

EXPOSE 3000

# Production start. NOTE: docker-compose (Task 13) overrides this CMD with
# `pnpm dev` (hot reload + bind-mounted source) for local development.
CMD ["pnpm", "start"]
