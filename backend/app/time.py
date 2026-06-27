"""Project-wide UTC timestamp helper.

Naive-UTC convention: all timestamps are stored as ``TIMESTAMP WITHOUT TIME ZONE``
in Postgres, so asyncpg rejects tz-aware datetimes.  Always use ``now_utc()``
instead of ``datetime.utcnow()`` (deprecated) or a tz-aware ``datetime.now(UTC)``.
"""

from datetime import UTC, datetime


def now_utc() -> datetime:
    """Return the current UTC time as a naive datetime (no tzinfo).

    Strips tzinfo so asyncpg accepts the value on ``TIMESTAMP WITHOUT TIME ZONE``
    columns.  Postgres is strict; SQLite (used in tests) is lenient and does not
    surface the mismatch.
    """
    return datetime.now(UTC).replace(tzinfo=None)
