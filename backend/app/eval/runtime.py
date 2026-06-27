"""Runtime end-of-conversation judge for the Zapp Global Philosophy School backend.

Two public symbols consumed by the application layer:

``evaluate_conversation``
    Asynchronous judge over the full conversation transcript.  Persists a
    ``SessionGrade`` row, sets ``ConversationSession.graded_at``, and emits
    observability events.  Wraps every error in try/except -- never raises to
    the caller.
    req: evaluation-016, evaluation-017, evaluation-019

``idle_sweep_once``
    Grades all sessions idle longer than ``Settings.conversation_idle_timeout``
    with no ``graded_at`` timestamp.  Respects ``Settings.runtime_eval_enabled``.
    Returns the count of sessions graded in this sweep.
    req: evaluation-014

NOTE: the ``is_goodbye`` keyword-heuristic function has been removed (evaluation-015).
End-of-conversation intent is now detected by the orchestrator's ``end_session`` tool
(``app/agents/orchestrator.py``), which sets ``AgentDeps.session_ended = True`` and
signals ``app/api/chat.py`` to schedule ``evaluate_conversation`` as a background task.

Judge model + thresholds are read exclusively from ``evals.config`` -- the single
source of truth shared by the offline CI suite and this runtime judge, ensuring
offline and production grades are directly comparable.

Observability ownership:
- **Logfire**: full detail including content (Logfire scrubs PII by default).
- **PostHog**: metadata-ONLY (session_id, score, needs_review).  Student message
  content is NEVER forwarded to PostHog because PostHog does not scrub PII.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import logfire
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.session import (
    ConversationSession,
    SessionGrade,
    SessionRepository,
)
from app.config import get_settings
from app.observability import get_posthog
from app.time import now_utc

# evals.* is a sibling package in the backend root (not an installed third-party
# library).  The ``[[tool.mypy.overrides]]`` entry in pyproject.toml sets
# ``follow_imports = "silent"`` for ``evals.*``, which tells mypy to follow and
# use the types from those modules but suppress any errors originating inside
# them.  The import is LAZY in terms of API calls: importing the module never
# constructs the judge Agent and never reads PYDANTIC_AI_GATEWAY_API_KEY --
# that only happens when ``judge_text(...)`` is actually awaited.
from evals.config import JUDGE_MODEL, THRESHOLDS
from evals.judge import judge_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transcript rendering  (private helper)
# ---------------------------------------------------------------------------


def _render_transcript(messages: list[ModelMessage]) -> str:
    """Convert a list of ``ModelMessage`` objects into a readable transcript.

    Produces ``User: <text>`` / ``Assistant: <text>`` lines, one per message
    part.  Multi-modal user content is flattened to the text strings it
    contains; non-text parts (images, audio, etc.) are silently omitted since
    the judge only needs the conversational text to assign a quality score.

    Args:
        messages: Ordered list of ``ModelMessage`` objects from
            ``ModelMessagesTypeAdapter.validate_json``.

    Returns:
        A plain-text transcript string, or ``"(empty conversation)"`` when no
        renderable parts are found.
    """
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for req_part in msg.parts:
                if isinstance(req_part, UserPromptPart):
                    content = req_part.content
                    if isinstance(content, str):
                        lines.append(f"User: {content}")
                    else:
                        # Sequence[UserContent]: keep only raw str items.
                        text_items = [item for item in content if isinstance(item, str)]
                        if text_items:
                            lines.append(f"User: {' '.join(text_items)}")
        elif isinstance(msg, ModelResponse):
            for resp_part in msg.parts:
                if isinstance(resp_part, TextPart):
                    lines.append(f"Assistant: {resp_part.content}")
    return "\n".join(lines) if lines else "(empty conversation)"


# ---------------------------------------------------------------------------
# evaluate_conversation  (req: evaluation-016, evaluation-017, evaluation-019)
# ---------------------------------------------------------------------------


async def evaluate_conversation(db: AsyncSession, session_id: str) -> None:
    """Grade a finished conversation, persist the result, and emit observability.

    Workflow:
    1. Load ``message_history`` via ``SessionRepository.load_messages``.
    2. Render a plain-text transcript.
    3. Call ``judge_text(transcript)`` -- structured int judge (1-5, temp 0).
    4. Persist :class:`~app.agents.session.SessionGrade` (score, needs_review,
       model, created_at) and set
       :attr:`~app.agents.session.ConversationSession.graded_at`.
    5. Emit a Logfire span (full detail -- content is safe here, Logfire scrubs
       PII by default).
    6. Emit a PostHog event with **metadata only** (session_id, score,
       needs_review -- no message content, since PostHog does not scrub PII).

    **Never raises** -- all exceptions are caught, logged as ``WARNING``, and the
    function returns ``None`` so the caller is never disrupted.

    Args:
        db: Open :class:`AsyncSession`; owned by the caller.  This function
            flushes and commits inside the try block.
        session_id: Identifier of the session to grade.

    req: evaluation-016, evaluation-017, evaluation-019
    """
    try:
        messages = await SessionRepository(db).load_messages(session_id)
        transcript: str = _render_transcript(messages) if messages else "(no messages)"

        score: int = await judge_text(transcript)

        needs_review: bool = score < THRESHOLDS["judge_mean"]
        grade = SessionGrade(
            session_id=session_id,
            score=score,
            rationale="",
            needs_review=needs_review,
            model=JUDGE_MODEL,
            created_at=now_utc(),
        )
        db.add(grade)
        await db.flush()

        # Update the parent session's graded_at so the idle sweep does not
        # re-grade an already-evaluated session.
        stmt = select(ConversationSession).where(
            ConversationSession.id == session_id  # type: ignore[arg-type]
        )
        result = await db.execute(stmt)
        session_row: ConversationSession | None = result.scalar_one_or_none()
        if session_row is not None:
            session_row.graded_at = now_utc()
            db.add(session_row)

        await db.commit()

        # Logfire: engineering observability -- content + cost captured here.
        logfire.info(
            "conversation_eval",
            session_id=session_id,
            score=score,
            needs_review=needs_review,
        )

        # PostHog: product analytics -- METADATA ONLY.  Do not include transcript
        # or any student-message text; PostHog does not scrub PII by default.
        ph = get_posthog()
        if ph is not None:
            ph.capture(
                session_id,
                "conversation_evaluated",
                {
                    "session_id": session_id,
                    "score": score,
                    "needs_review": needs_review,
                },
            )
    except Exception as exc:
        logger.warning(
            "evaluate_conversation failed for session %r: %s",
            session_id,
            exc,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# idle_sweep_once  (req: evaluation-014)
# ---------------------------------------------------------------------------


async def idle_sweep_once(db: AsyncSession) -> int:
    """Grade all idle, un-graded sessions in one sweep.

    Queries :class:`~app.agents.session.ConversationSession` rows where:
    - ``updated_at`` is older than ``Settings.conversation_idle_timeout``
      seconds ago (the session has been idle long enough to be considered ended).
    - ``graded_at IS NULL`` (not yet evaluated).

    Calls :func:`evaluate_conversation` for each matching session.  Each call
    commits inside its own try/except so one session's failure does not prevent
    the others from being graded.

    Respects ``Settings.runtime_eval_enabled`` -- returns ``0`` immediately when
    the flag is ``False``.

    Args:
        db: Open :class:`AsyncSession` shared across all grading calls in this
            sweep.  ``evaluate_conversation`` commits after each session.

    Returns:
        Number of sessions graded during this sweep.

    req: evaluation-014
    """
    settings = get_settings()
    if not settings.runtime_eval_enabled:
        return 0

    cutoff = now_utc() - timedelta(seconds=settings.conversation_idle_timeout)

    stmt = (
        select(ConversationSession)
        .where(ConversationSession.updated_at < cutoff)  # type: ignore[arg-type]
        .where(ConversationSession.graded_at.is_(None))  # type: ignore[union-attr]
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Collect IDs before iterating: evaluate_conversation commits and may
    # expire the ORM objects depending on session configuration.
    session_ids = [s.id for s in sessions]

    count = 0
    for sid in session_ids:
        await evaluate_conversation(db, sid)
        count += 1
    return count
