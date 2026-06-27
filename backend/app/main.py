"""ASGI entrypoint — builds the FastAPI app, wires observability and routers.

Exposes the ASGI ``app`` so ``uvicorn app.main:app`` works (matches the docker /
railway start command). Observability is wired from the ``lifespan`` startup handler
rather than at import time, so ``import app.main`` succeeds with NO env set:
:func:`configure_observability` itself is token-gated and no-ops safely on missing
settings/tokens, and constructing ``FastAPI`` + adding ``CORSMiddleware`` reads no
secrets. CORS is permissive for dev — the local frontend origin plus a regex for
Vercel preview deployments.

Requirements: platform-scaffold-008 (mounts ``GET /health``),
platform-scaffold-009 (mounts ``POST /chat``).
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, health
from app.config import get_settings
from app.db import get_sessionmaker
from app.eval.runtime import idle_sweep_once
from app.observability import configure_observability

# Dev CORS: the local Next.js origin plus a regex matching Vercel preview URLs. Methods
# and headers stay permissive for local development; tightened per-env later.
_DEV_ALLOW_ORIGINS = ["http://localhost:3000"]
_VERCEL_PREVIEW_REGEX = r"https://.*\.vercel\.app"

_log = logging.getLogger(__name__)

# Idle-sweep fires every ~60 s.  Sleeping FIRST means the task does not touch the DB
# at startup — and is cancelled before waking during short-lived TestClient runs.
_SWEEP_INTERVAL_SECONDS: int = 60


async def _idle_sweep_loop() -> None:
    """Background coroutine: grade idle sessions every ~``_SWEEP_INTERVAL_SECONDS`` s.

    Sleeps *before* the first sweep so the task does not fire at startup (or during
    TestClient runs where the lifespan is invoked briefly and then torn down). Each
    iteration opens and closes its own ``AsyncSession`` independently; a sweep error is
    logged as WARNING and the loop continues so a transient DB blip never kills the app.

    req: evaluation-014, evaluation-018
    """
    while True:
        # Sleep first — ``asyncio.CancelledError`` propagates here on shutdown.
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        try:
            async with get_sessionmaker()() as db:
                count = await idle_sweep_once(db)
                await db.commit()
            if count:
                _log.info("idle_sweep_loop: graded %d session(s)", count)
        except Exception:
            _log.warning("idle_sweep_loop: sweep error (will retry next interval)", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Wire observability and shared resources at startup; clean up on exit.

    The shared ``httpx.AsyncClient`` is stored on ``app.state.http_client`` for
    future integrations (e.g. direct route-level access to the geo/locale client).
    The ``/chat`` handler additionally creates a per-request client so it stays
    decoupled from the lifespan context.  The client stored here is available to
    any route or middleware that reads ``request.app.state.http_client``.

    WHERE ``runtime_eval_enabled``, an asyncio background task (``_idle_sweep_loop``)
    is started during startup and cancelled + awaited cleanly on shutdown.

    req: evaluation-014, evaluation-018
    """
    sweep_task: asyncio.Task[None] | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http_client:
        app.state.http_client = http_client
        configure_observability(app)

        # Start the idle-sweep background task when the runtime judge is enabled.
        # Guard: if Settings cannot be loaded (e.g. required env vars absent in some
        # test environments such as test_health.py), skip the task rather than crash.
        # req: evaluation-014, evaluation-018
        try:
            _runtime_eval_enabled = get_settings().runtime_eval_enabled
        except Exception:
            _runtime_eval_enabled = False

        if _runtime_eval_enabled:
            sweep_task = asyncio.create_task(_idle_sweep_loop(), name="idle_sweep_loop")

        try:
            yield
        finally:
            # Cancel + await the sweep task on shutdown (graceful or forced).
            if sweep_task is not None:
                sweep_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sweep_task


app = FastAPI(title="Zapp Philosophy School API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ALLOW_ORIGINS,
    allow_origin_regex=_VERCEL_PREVIEW_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(documents.router)
