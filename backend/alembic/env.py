"""Alembic migration environment.

Reads the database URL from the single config source (``app.config.get_settings``)
rather than from ``alembic.ini`` so credentials are never hardcoded. Migrations run
synchronously, so the async ``postgresql+asyncpg://`` URL from settings is reduced to a
plain ``postgresql://`` URL here (SQLAlchemy resolves the installed sync DBAPI at
runtime); credentials are reused unchanged.

Requirements: platform-scaffold-006 (the DB seam migrations target),
platform-scaffold-007 (the baseline that enables the ``vector`` extension).
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import get_settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _sync_database_url() -> str:
    """Return a synchronous Postgres URL derived from ``settings.database_url``.

    The app talks to Postgres asynchronously (``postgresql+asyncpg://``); Alembic runs
    synchronously. Stripping the ``+asyncpg`` driver yields a plain ``postgresql://`` URL
    that defers sync-DBAPI selection to the driver installed in the runtime image.
    """
    return get_settings().database_url.replace("+asyncpg", "")


# Override the ini placeholder with the resolved (credential-free in source) URL.
config.set_main_option("sqlalchemy.url", _sync_database_url())

# No ORM metadata is targeted; the baseline only manages the ``vector`` extension and
# feature tables arrive with their own features/migrations.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
