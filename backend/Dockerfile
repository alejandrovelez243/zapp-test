# Backend image — FastAPI + uv. (req: platform-scaffold-002, platform-scaffold-019)
#
# Build context is ./backend (see docker-compose `build: ./backend` and
# `docker build ./backend`); paths below are relative to that context.
#
# Install is ALWAYS `uv sync --frozen` — the committed uv.lock is authoritative.
# NEVER `uv add` in the image: a drifted lock must fail the build, not silently
# re-resolve to a different dependency set.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# uv runtime/build behaviour:
#   UV_FROZEN          — never re-resolve or rewrite the lock; treat uv.lock as truth.
#   UV_COMPILE_BYTECODE — precompile .pyc at install time for faster cold starts.
#   UV_LINK_MODE=copy  — copy from the cache mount instead of hardlinking across
#                        filesystems (avoids the cross-device hardlink warning in Docker).
ENV UV_FROZEN=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# --- Dependency layer ---------------------------------------------------------
# Copy ONLY the manifests first so this layer is cached on (pyproject.toml, uv.lock)
# and is not invalidated by application-code edits. The project itself is a
# non-packaged ("virtual") uv project (no [build-system] in pyproject.toml), so
# `uv sync` installs dependencies only and does not need app/ to be present yet.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Application layer --------------------------------------------------------
# Copy the whole build context (the backend root) AFTER `uv sync` so the cached
# dependency layer above is never invalidated by an application-code edit. We copy
# everything rather than enumerating dirs (app/, alembic/, evals/, alembic.ini, ...)
# because a runtime import of a non-listed dir is a silent boot footgun — e.g.
# app/eval/runtime.py imports `evals.config`/`evals.judge`, so a missing `COPY evals/`
# crashes the backend on boot with `ModuleNotFoundError: No module named 'evals'`.
# .dockerignore is the contract that keeps this lean and safe: it MUST exclude
# .venv (or the host venv would clobber the image's), .env, and the caches.
COPY . .

# Put the project venv first on PATH so `python`/`alembic`/`uvicorn` resolve to it.
ENV PATH="/app/.venv/bin:$PATH"

# Run as an unprivileged user. /app (incl. .venv) is chowned so `uv run` can take
# its environment lock without needing root at runtime.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Migrate-then-serve: apply migrations once on boot (CREATE EXTENSION vector +
# future schema), then start uvicorn. `${PORT:-8000}` lets Railway inject $PORT
# while defaulting to 8000 for local/compose. The env is already synced from the
# same frozen lock above, so `uv run` is a no-op sync and just executes.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
