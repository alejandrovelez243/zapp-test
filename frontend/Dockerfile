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

# corepack ships with Node 22 and manages pnpm without a global install.
# Pin pnpm@9 (major) to match CI (`corepack prepare pnpm@9 --activate` in
# ci.yml) and to match the lockfileVersion 9.0 in pnpm-lock.yaml.
# IMPORTANT: without an explicit version pin, corepack downloads pnpm 11+,
# which no longer reads the `pnpm.onlyBuiltDependencies` field in package.json
# and exits 1 with ERR_PNPM_IGNORED_BUILDS for sharp + unrs-resolver.
RUN corepack enable && corepack prepare pnpm@9 --activate

WORKDIR /app

# --- Dependency layer ---------------------------------------------------------
# Copy manifests first so this layer is cached on manifest changes and survives
# source edits.
#
# pnpm 9 reads `"pnpm": {"onlyBuiltDependencies": [...]}` from package.json to
# approve build scripts for sharp + unrs-resolver (ERR_PNPM_IGNORED_BUILDS
# guard). No pnpm-workspace.yaml is needed — this is a single-package repo and
# a workspace file without a `packages:` field causes pnpm to abort in workspace
# mode, which is why the stray frontend/pnpm-workspace.yaml was deleted.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# --- Application layer + production build -------------------------------------
COPY . .
RUN pnpm build

EXPOSE 3000

# Production start. NOTE: docker-compose (Task 13) overrides this CMD with
# `pnpm dev` (hot reload + bind-mounted source) for local development.
CMD ["pnpm", "start"]
