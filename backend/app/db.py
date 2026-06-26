"""Async database engine + session factory + FastAPI session dependency.

Owns the SQLAlchemy async seam over Postgres (asyncpg). The engine and session
factory are created LAZILY (mirroring ``config.get_settings``) so that importing this
module never instantiates :class:`Settings` (which has required fields) nor opens a DB
connection — static analysis / CI import checks must succeed with no env set. No tables
are defined here; feature tables (``Document`` / ``ConversationSession`` / ...) arrive
with their own features.

Requirement: platform-scaffold-006 (supporting — the async DB seam consumed once
migrations have run and feature tables exist).
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the cached, process-wide async engine.

    Lazy + cached so importing this module neither reads env (via ``get_settings``) nor
    constructs an engine; the asyncpg connection pool is created on first use. Expects an
    ``postgresql+asyncpg://...`` URL from settings.
    """
    return create_async_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the cached ``async_sessionmaker`` bound to :func:`get_engine`.

    ``expire_on_commit=False`` keeps ORM objects usable after commit (objects returned to
    request handlers are not re-fetched on attribute access).
    """
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped :class:`AsyncSession`.

    Commits on success, rolls back on any exception, and always closes the session via the
    async context manager (which returns the connection to the pool).
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
