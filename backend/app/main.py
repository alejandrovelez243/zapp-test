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

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, health
from app.observability import configure_observability

# Dev CORS: the local Next.js origin plus a regex matching Vercel preview URLs. Methods
# and headers stay permissive for local development; tightened per-env later.
_DEV_ALLOW_ORIGINS = ["http://localhost:3000"]
_VERCEL_PREVIEW_REGEX = r"https://.*\.vercel\.app"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Wire observability and shared resources at startup; clean up on exit.

    The shared ``httpx.AsyncClient`` is stored on ``app.state.http_client`` for
    future integrations (e.g. direct route-level access to the geo/locale client).
    The ``/chat`` handler additionally creates a per-request client so it stays
    decoupled from the lifespan context.  The client stored here is available to
    any route or middleware that reads ``request.app.state.http_client``.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http_client:
        app.state.http_client = http_client
        configure_observability(app)
        yield


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
