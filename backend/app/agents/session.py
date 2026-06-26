"""ConversationSession SQLModel table — per-session language state.

One row per chat session.  Loaded at the start of each ``/chat`` turn to recover the
locked ``active_lang`` and the auto-switch counters; updated (committed) after the
orchestrator run completes.

Requirement: multilingual-007
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _now_utc() -> datetime:
    """Return the current UTC time (timezone-aware).

    Used as the ``default_factory`` for timestamp columns so mypy-strict sees a
    concrete return type rather than an untyped lambda.
    """
    return datetime.now(UTC)


class ConversationSession(SQLModel, table=True):
    """One row per chat session; keyed by the caller-supplied ``session_id``.

    Fields
    ------
    id:
        Externally supplied session identifier (primary key).
    active_lang:
        ISO 639-1 code the session is currently locked to (``es`` | ``en`` | ``pt``),
        or ``None`` before the first turn completes.  Written by
        ``resolve_active_lang`` on every turn.
    last_supported_lang:
        The most recent supported language that was positively detected — used by the
        auto-switch counter when ``lang_autoswitch`` is enabled.
    pending_switch_lang:
        Candidate language being accumulated toward an auto-switch.  Reset whenever
        the detected language changes or a switch fires.
    pending_switch_count:
        Consecutive turns where ``pending_switch_lang`` was detected.  A switch fires
        when this reaches ``config.autoswitch_min_turns`` (default 2).
    created_at:
        Row creation timestamp (UTC); set once at session creation.
    updated_at:
        Last-updated timestamp (UTC); refreshed on every turn.  The application layer
        is responsible for updating this field before each commit.
    """

    # req: multilingual-007 — primary key is the externally supplied session id
    id: str = Field(primary_key=True)

    # req: multilingual-007 — language state fields for the session
    active_lang: str | None = None
    last_supported_lang: str | None = None
    pending_switch_lang: str | None = None
    pending_switch_count: int = 0

    # Timestamp fields — default_factory keeps mypy-strict happy (no uninitialized
    # non-optional fields) while ensuring the application always supplies a concrete
    # value rather than relying on a server default.
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
