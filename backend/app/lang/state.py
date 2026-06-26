"""Language-session state machine — pure function, no I/O.

Implements ``resolve_active_lang(session, det, config) -> ActiveLangDecision``.

Satisfies:
  multilingual-003 — active_lang constrained to es/en/pt or fallback
  multilingual-004 — first-turn lock to detected supported language
  multilingual-008 — locked + unsupported → keep + needs_review
  multilingual-009 — first-turn + unsupported → fallback_lang + needs_review + fallback_used
  multilingual-011 — short/unreliable input → no language switch, pending counters unchanged
  multilingual-014 — lang_autoswitch disabled → hard session lock for the whole session

Design contract: specs/multilingual/design.md §2.3
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.session import ConversationSession
from app.config import Settings, get_settings
from app.lang.detector import DetectionResult


class ActiveLangDecision(BaseModel):
    """Output of the per-turn language state machine.

    The ``/chat`` boundary persists ``active_lang``, ``pending_switch_lang``, and
    ``pending_switch_count`` back to the ``ConversationSession`` row after each turn.

    Fields
    ------
    active_lang:
        The language code (``es`` | ``en`` | ``pt``) to use for this turn.
        Satisfies multilingual-003 — always one of the supported codes or the
        configured fallback (which is also a supported code).
    first_turn:
        ``True`` when ``session.active_lang`` was ``None`` (no prior lock exists).
    locked:
        ``True`` when the session now has a locked ``active_lang``. Always ``True``
        once any turn has completed.
    switched:
        ``True`` when the auto-switch counter reached the threshold and
        ``active_lang`` changed this turn (multilingual-013).
    fallback_used:
        ``True`` when the detected language was unsupported and the configured
        ``fallback_lang`` was applied (multilingual-009).
    needs_review:
        ``True`` when human review is warranted — set for unsupported languages and
        fallback use; the output_validator may also set it for low confidence /
        detector failure.
    reasons:
        Machine-readable reason codes appended this turn (append-only per turn).
    pending_switch_lang:
        Candidate language being accumulated toward an auto-switch; caller persists.
    pending_switch_count:
        Consecutive turns where ``pending_switch_lang`` was detected; caller persists.
        A switch fires when this reaches ``config.autoswitch_min_turns``.
    """

    # req: multilingual-003 — must be es | en | pt (fallback_lang is always in supported)
    active_lang: str
    first_turn: bool
    locked: bool
    switched: bool = False
    fallback_used: bool = False
    needs_review: bool = False
    reasons: list[str] = Field(default_factory=list)
    # Auto-switch counters — caller persists these to ConversationSession
    pending_switch_lang: str | None = None
    pending_switch_count: int = 0


def resolve_active_lang(
    session: ConversationSession,
    det: DetectionResult,
    config: Settings | None = None,
) -> ActiveLangDecision:
    """Decide the ``active_lang`` for the current turn.

    Pure state machine — reads ``session`` and ``det``; performs **no** database
    writes.  The caller is responsible for persisting the returned counters
    (``pending_switch_lang``, ``pending_switch_count``) and the new ``active_lang``
    back to ``ConversationSession``.

    Parameters
    ----------
    session:
        The current ``ConversationSession`` row.  ``session.active_lang`` is
        ``None`` on the session's first turn.
    det:
        ``DetectionResult`` from the lingua detector for the incoming message.
        ``det.lang`` may be ``None`` when detection fails (req: multilingual-012).
    config:
        Application settings.  When ``None``, ``get_settings()`` is called once and
        its cached result is used — callers that already have the settings object
        should pass it explicitly to avoid any import-time side effects.

    Returns
    -------
    ActiveLangDecision
        Contains the resolved ``active_lang``, status flags, and the updated
        auto-switch counters to persist.
    """
    cfg: Settings = config if config is not None else get_settings()

    # ------------------------------------------------------------------
    # FIRST TURN — session.active_lang is None (no existing lock)
    # ------------------------------------------------------------------
    if session.active_lang is None:
        if det.lang is not None and det.lang in cfg.supported:
            # req: multilingual-004 — lock to the detected supported language on first turn
            return ActiveLangDecision(
                active_lang=det.lang,
                first_turn=True,
                locked=True,
            )
        # req: multilingual-009 — unsupported lang (or detection failure) on first turn
        # → fall back to configured fallback_lang, signal needs_review
        return ActiveLangDecision(
            active_lang=cfg.fallback_lang,
            first_turn=True,
            locked=True,
            fallback_used=True,
            needs_review=True,
            reasons=["unsupported-first-turn"],
        )

    # ------------------------------------------------------------------
    # LOCKED SESSION — session.active_lang is already set
    # req: multilingual-007 — base is the existing locked language
    # ------------------------------------------------------------------
    base_lang: str = session.active_lang

    # -- Unsupported language on a locked session (always fires, flag-independent)
    # req: multilingual-008 — keep active_lang + needs_review regardless of autoswitch
    if det.lang is not None and det.lang not in cfg.supported:
        return ActiveLangDecision(
            active_lang=base_lang,
            first_turn=False,
            locked=True,
            needs_review=True,
            reasons=["unsupported-on-locked"],
            pending_switch_lang=session.pending_switch_lang,
            pending_switch_count=session.pending_switch_count,
        )

    # -- Detection failure on a locked session (det.lang is None)
    # Keep active_lang unchanged; output_validator handles needs_review via
    # lang_confidence (req: multilingual-012 owned by the validator, not here).
    if det.lang is None:
        return ActiveLangDecision(
            active_lang=base_lang,
            first_turn=False,
            locked=True,
            pending_switch_lang=session.pending_switch_lang,
            pending_switch_count=session.pending_switch_count,
        )

    # -- Short / unreliable input — no switch, pending counters unchanged
    # req: multilingual-011 — is_reliable=False means input is below min_input_chars
    if not det.is_reliable:
        return ActiveLangDecision(
            active_lang=base_lang,
            first_turn=False,
            locked=True,
            pending_switch_lang=session.pending_switch_lang,
            pending_switch_count=session.pending_switch_count,
        )

    # At this point:
    #   det.lang is a supported language (str, not None, in cfg.supported)
    #   det.is_reliable is True
    #   session.active_lang is set (base_lang is a str)

    # -- Autoswitch disabled → hard session lock
    # req: multilingual-014 — keep first-turn active_lang for the whole session
    if not cfg.lang_autoswitch:
        return ActiveLangDecision(
            active_lang=base_lang,
            first_turn=False,
            locked=True,
            pending_switch_lang=session.pending_switch_lang,
            pending_switch_count=session.pending_switch_count,
        )

    # -- Autoswitch enabled — count consecutive turns in a new supported language
    # req: multilingual-013 — switch only after autoswitch_min_turns consecutive turns
    # NOTE: Task 11 owns the lang_autoswitch feature flag; here we implement the
    # counting logic so Task 11 can enable it without further changes.
    if det.lang != base_lang:
        count: int = (
            session.pending_switch_count + 1 if session.pending_switch_lang == det.lang else 1
        )
        if count >= cfg.autoswitch_min_turns:
            # Switch fires — reset pending counters.
            return ActiveLangDecision(
                active_lang=det.lang,
                first_turn=False,
                locked=True,
                switched=True,
                pending_switch_lang=None,
                pending_switch_count=0,
            )
        # Accumulate — not enough consecutive turns yet; keep base_lang.
        return ActiveLangDecision(
            active_lang=base_lang,
            first_turn=False,
            locked=True,
            pending_switch_lang=det.lang,
            pending_switch_count=count,
        )

    # Same language as the locked one — keep; reset any stale pending counters.
    return ActiveLangDecision(
        active_lang=base_lang,
        first_turn=False,
        locked=True,
        pending_switch_lang=None,
        pending_switch_count=0,
    )
