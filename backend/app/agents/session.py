"""ConversationSession SQLModel table + SessionRepository.

One row per chat session.  Loaded at the start of each ``/chat`` turn to recover the
locked ``active_lang`` and the auto-switch counters; updated (committed) after the
orchestrator run completes.

Task 7 adds:
  * ``history_json`` nullable column on :class:`ConversationSession`.
  * :class:`SessionRepository` — stateful repository that owns an
    :class:`~sqlalchemy.ext.asyncio.AsyncSession` and exposes four async methods:
    :meth:`~SessionRepository.get_or_create`, :meth:`~SessionRepository.update_language_state`,
    :meth:`~SessionRepository.load_messages`, :meth:`~SessionRepository.save_messages`.

faq-rag-019 adds:
  * ``faq_history_json`` nullable column on :class:`ConversationSession` (migration 0006).
  * :meth:`~SessionRepository.load_faq_messages` / :meth:`~SessionRepository.save_faq_messages`
    — mirrors the orchestrator history helpers but stores the FAQ sub-agent's own turn
    history so it accumulates context across turns independently of the orchestrator.

Requirement: multilingual-007, faq-rag-019
"""

from datetime import datetime

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel

from app.time import now_utc


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
    history_json:
        JSON-serialised ``list[ModelMessage]`` produced by
        ``ModelMessagesTypeAdapter.dump_json(result.all_messages())``.  ``None`` before
        the first turn's messages are persisted.  Stored as ``TEXT`` so it works across
        all Postgres versions without a JSON operator dependency.
    graded_at:
        Timestamp (naive-UTC) set by the runtime evaluator after a ``SessionGrade``
        row is persisted.  ``None`` until the conversation has been graded.  Used by
        the idle-sweep guard to avoid re-grading sessions already evaluated.
        req: evaluation-016, evaluation-018
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
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    # req: multilingual-007 — message history for coherence replay
    # Serialised via ModelMessagesTypeAdapter; null until the first turn completes.
    history_json: str | None = None

    # req: faq-rag-019 — FAQ sub-agent's own per-session message history.
    # Stored separately from history_json (orchestrator history) so the FAQ agent
    # accumulates its own context independently.  Null until the first FAQ turn.
    faq_history_json: str | None = None

    # req: evaluation-016, evaluation-018 — sweep guard; None until graded.
    graded_at: datetime | None = None


class SessionGrade(SQLModel, table=True):
    """Persisted evaluation score for a completed conversation.

    Written by ``evaluate_conversation`` (runtime judge) after the structured
    judge returns a 1-5 score over the full transcript.  One row per graded
    session; the idle-sweep uses ``ConversationSession.graded_at IS NULL`` to
    find un-graded sessions.

    Fields
    ------
    id:
        Auto-increment surrogate key.
    session_id:
        Foreign key (by convention, not constraint) to ``ConversationSession.id``.
        Indexed for fast lookup by session.
    score:
        Discrete judge score 1-5 (1 = harmful/off-language, 5 = fully correct).
    rationale:
        Free-text explanation from the judge run; empty string when unavailable.
    needs_review:
        ``True`` when ``score < THRESHOLDS["judge_mean"]``; flags sessions for
        human review in the admin dashboard.
    model:
        The judge model id used to produce this grade (e.g.
        ``"gateway/openai:gpt-4.1-mini"``); stored for audit / model-drift tracking.
    created_at:
        Row creation timestamp (naive-UTC); set at persist time.

    req: evaluation-016
    """

    # req: evaluation-016 — surrogate PK (auto-increment)
    id: int | None = Field(default=None, primary_key=True)

    # req: evaluation-016 — link back to the conversation; indexed for fast lookup
    session_id: str = Field(index=True)

    # req: evaluation-016 -- discrete 1-5 judge score
    score: int

    # Judge rationale (optional; empty string when not returned)
    rationale: str = ""

    # req: evaluation-016 — flags sessions scoring below judge_mean threshold
    needs_review: bool = False

    # req: evaluation-016 — audit trail: which judge model produced this grade
    model: str

    # req: evaluation-016 — naive-UTC creation timestamp; default set at insert time
    created_at: datetime = Field(default_factory=now_utc)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class SessionRepository:
    """Stateful repository for :class:`ConversationSession` persistence.

    Binds a single :class:`~sqlalchemy.ext.asyncio.AsyncSession` at construction
    time and exposes the four async persistence operations as instance methods.
    The caller (FastAPI boundary, background task) owns the ``db`` lifecycle and
    the final ``commit``; this class only flushes within each operation.

    Requirement: multilingual-007
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(self, session_id: str) -> ConversationSession:
        """Return the existing :class:`ConversationSession` or insert a fresh one.

        If no row exists for *session_id* a new :class:`ConversationSession` is
        created with ``created_at``/``updated_at`` set to UTC-now, added to the
        session, and flushed into the current transaction (so subsequent calls in
        the same request see it).

        The caller owns the final ``commit``.

        Requirement: multilingual-007
        """
        stmt = select(ConversationSession).where(
            ConversationSession.id == session_id  # type: ignore[arg-type]
        )
        result = await self.db.execute(stmt)
        existing: ConversationSession | None = result.scalar_one_or_none()
        if existing is not None:
            return existing

        now = now_utc()
        new_session = ConversationSession(
            id=session_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(new_session)
        await self.db.flush()  # make the row visible within this transaction
        return new_session

    async def update_language_state(
        self,
        session: ConversationSession,
        *,
        active_lang: str | None,
        last_supported_lang: str | None,
        pending_switch_lang: str | None,
        pending_switch_count: int,
    ) -> None:
        """Persist language-state fields on *session* and bump ``updated_at``.

        All four language-state fields are written (callers always supply the full
        current state after ``resolve_active_lang``).  The caller owns the final
        ``commit``.

        Requirement: multilingual-007
        """
        session.active_lang = active_lang
        session.last_supported_lang = last_supported_lang
        session.pending_switch_lang = pending_switch_lang
        session.pending_switch_count = pending_switch_count
        session.updated_at = now_utc()
        self.db.add(session)
        await self.db.flush()

    async def load_messages(self, session_id: str) -> list[ModelMessage] | None:
        """Return the persisted message history for *session_id*, or ``None``.

        Deserialises ``history_json`` via ``ModelMessagesTypeAdapter.validate_json``.
        Returns ``None`` when the row does not exist or ``history_json`` is
        null/empty — callers pass the result directly as ``message_history=`` to
        the agent run (``None`` starts a fresh context, consistent with the
        pydantic-ai convention).

        Requirement: multilingual-007
        """
        stmt = select(ConversationSession).where(
            ConversationSession.id == session_id  # type: ignore[arg-type]
        )
        result = await self.db.execute(stmt)
        row: ConversationSession | None = result.scalar_one_or_none()
        if row is None or not row.history_json:
            return None
        return ModelMessagesTypeAdapter.validate_json(row.history_json)

    async def save_messages(
        self,
        session_id: str,
        messages: list[ModelMessage],
    ) -> None:
        """Serialise *messages* and store them in the ``history_json`` column.

        Serialises via ``ModelMessagesTypeAdapter.dump_json`` (returns ``bytes``),
        decodes to UTF-8 ``str``, and stores in ``history_json`` on the existing
        session row.

        Raises ``ValueError`` if no row exists for *session_id* — callers must call
        :meth:`get_or_create` before :meth:`save_messages`.  The caller owns the
        final ``commit``.

        Requirement: multilingual-007
        """
        stmt = select(ConversationSession).where(
            ConversationSession.id == session_id  # type: ignore[arg-type]
        )
        result = await self.db.execute(stmt)
        row: ConversationSession | None = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"Session {session_id!r} not found; call get_or_create first.")
        row.history_json = ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")
        self.db.add(row)
        await self.db.flush()

    async def load_faq_messages(self, session_id: str) -> list[ModelMessage] | None:
        """Return the persisted FAQ sub-agent history for *session_id*, or ``None``.

        Deserialises ``faq_history_json`` via ``ModelMessagesTypeAdapter.validate_json``.
        Returns ``None`` when the row does not exist or ``faq_history_json`` is
        null/empty — callers pass the result directly as ``message_history=`` to the
        FAQ agent run (``None`` starts a fresh context, matching pydantic-ai convention).

        Mirrors :meth:`load_messages` but reads ``faq_history_json`` so the FAQ
        sub-agent has an independent conversation context from the orchestrator.

        req: faq-rag-019
        """
        stmt = select(ConversationSession).where(
            ConversationSession.id == session_id  # type: ignore[arg-type]
        )
        result = await self.db.execute(stmt)
        row: ConversationSession | None = result.scalar_one_or_none()
        if row is None or not row.faq_history_json:
            return None
        return ModelMessagesTypeAdapter.validate_json(row.faq_history_json)

    async def save_faq_messages(
        self,
        session_id: str,
        messages: list[ModelMessage],
    ) -> None:
        """Serialise *messages* and store them in the ``faq_history_json`` column.

        Serialises via ``ModelMessagesTypeAdapter.dump_json`` (returns ``bytes``),
        decodes to UTF-8 ``str``, and stores in ``faq_history_json`` on the existing
        session row.

        Raises ``ValueError`` if no row exists for *session_id* — callers must call
        :meth:`get_or_create` before :meth:`save_faq_messages`.  The caller owns the
        final ``commit``.

        Mirrors :meth:`save_messages` but writes to ``faq_history_json`` so the FAQ
        sub-agent accumulates its own history independently of the orchestrator.

        req: faq-rag-019
        """
        stmt = select(ConversationSession).where(
            ConversationSession.id == session_id  # type: ignore[arg-type]
        )
        result = await self.db.execute(stmt)
        row: ConversationSession | None = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"Session {session_id!r} not found; call get_or_create first.")
        row.faq_history_json = ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")
        self.db.add(row)
        await self.db.flush()
