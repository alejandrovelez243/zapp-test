"""Unit tests for resolve_active_lang — pure language-session state machine.

Covers every branch in state.py:
  (a) First turn: supported language → lock to detected language
  (b) First turn: unsupported language → fallback 'en' + needs_review
  (c) Locked session + lang_autoswitch=False → hard lock, no switch regardless of det.lang
  (d) Locked session + unsupported det.lang → keep active_lang + needs_review
  (e) Locked session + short/unreliable input → no switch, pending counters unchanged
  (f) Autoswitch ON: two consecutive reliable turns in a new language → switch fires

All tests are pure (no I/O, no DB, no async) — resolve_active_lang is a pure function.

req: multilingual-003, multilingual-004, multilingual-008, multilingual-009,
     multilingual-011, multilingual-013, multilingual-014
Design contract: specs/multilingual/design.md §2.3
"""

from __future__ import annotations

from app.agents.session import ConversationSession
from app.config import Settings
from app.lang.detector import DetectionResult
from app.lang.state import resolve_active_lang

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**overrides: object) -> Settings:
    """Return a Settings instance with test defaults and optional overrides.

    Passes ``database_url`` and ``admin_token`` so pydantic-settings required
    fields are satisfied without needing real environment variables.
    """
    return Settings(
        database_url="sqlite:///:memory:",
        admin_token="test-admin",
        **overrides,  # type: ignore[arg-type]
    )


def _fresh_session(session_id: str = "s1") -> ConversationSession:
    """Return a ConversationSession with no prior active_lang (first-turn state)."""
    return ConversationSession(id=session_id)


def _locked_session(
    active_lang: str,
    *,
    session_id: str = "s1",
    pending_switch_lang: str | None = None,
    pending_switch_count: int = 0,
) -> ConversationSession:
    """Return a ConversationSession already locked to *active_lang*."""
    s = ConversationSession(id=session_id)
    s.active_lang = active_lang
    s.pending_switch_lang = pending_switch_lang
    s.pending_switch_count = pending_switch_count
    return s


def _det(
    lang: str | None,
    *,
    confidence: float = 0.92,
    is_reliable: bool = True,
    error: str | None = None,
) -> DetectionResult:
    """Convenience constructor for DetectionResult."""
    return DetectionResult(
        lang=lang,
        confidence=confidence,
        is_reliable=is_reliable,
        error=error,
    )


# ===========================================================================
# (a) + (b) First turn: supported and unsupported language → lock / fallback
# req: multilingual-004, multilingual-009
# ===========================================================================


class TestResolveActiveLangFirstTurn:
    def test_first_turn_es_locks_to_es(self) -> None:
        """First-turn, reliable Spanish detection → active_lang='es', first_turn=True, locked.

        req: multilingual-004 — first-turn lock to detected supported language
        """
        decision = resolve_active_lang(_fresh_session(), _det("es"), _cfg())

        assert decision.active_lang == "es"
        assert decision.first_turn is True
        assert decision.locked is True
        assert decision.fallback_used is False
        assert decision.switched is False
        assert decision.needs_review is False

    def test_first_turn_en_locks_to_en(self) -> None:
        """First turn with English → locks to 'en'.

        req: multilingual-004
        """
        decision = resolve_active_lang(_fresh_session(), _det("en"), _cfg())
        assert decision.active_lang == "en"
        assert decision.first_turn is True
        assert decision.locked is True

    def test_first_turn_pt_locks_to_pt(self) -> None:
        """First turn with Portuguese → locks to 'pt'.

        req: multilingual-004
        """
        decision = resolve_active_lang(_fresh_session(), _det("pt"), _cfg())
        assert decision.active_lang == "pt"
        assert decision.first_turn is True
        assert decision.locked is True

    def test_first_turn_unsupported_de_falls_back_to_en(self) -> None:
        """First turn with German → fallback to 'en', fallback_used=True, needs_review=True.

        req: multilingual-009 — unsupported first-turn → fallback_lang + needs_review
        req: multilingual-004 — first_turn=True in all first-turn branches
        """
        decision = resolve_active_lang(_fresh_session(), _det("de"), _cfg())

        assert decision.active_lang == "en"
        assert decision.first_turn is True
        assert decision.locked is True
        assert decision.fallback_used is True
        assert decision.needs_review is True
        assert "unsupported-first-turn" in decision.reasons

    def test_first_turn_detection_failure_falls_back_to_en(self) -> None:
        """First turn when detector yields lang=None → fallback_lang + needs_review.

        req: multilingual-009, multilingual-012
        """
        decision = resolve_active_lang(
            _fresh_session(),
            _det(None, confidence=0.0, is_reliable=False, error="crash"),
            _cfg(),
        )

        assert decision.active_lang == "en"
        assert decision.fallback_used is True
        assert decision.needs_review is True

    def test_first_turn_fallback_lang_must_be_supported(self) -> None:
        """The fallback_lang returned on first-turn unsupported is always in the supported set.

        req: multilingual-003 — active_lang constrained to es/en/pt
        """
        cfg = _cfg()
        decision = resolve_active_lang(_fresh_session(), _det("zh"), cfg)
        assert decision.active_lang in cfg.supported


# ===========================================================================
# (c) + (d) + (e) Locked session: hard lock / unsupported lang / short input
# req: multilingual-008, multilingual-011, multilingual-014
# ===========================================================================


class TestResolveActiveLangLocked:
    def test_locked_es_autoswitch_off_keeps_es_on_pt_detection(self) -> None:
        """Locked='es', det='pt', autoswitch=False → stays 'es', no switch.

        req: multilingual-014 — hard lock keeps first-turn active_lang for whole session
        """
        decision = resolve_active_lang(
            _locked_session("es"),
            _det("pt"),
            _cfg(lang_autoswitch=False),
        )

        assert decision.active_lang == "es"
        assert decision.switched is False
        assert decision.first_turn is False
        assert decision.locked is True
        assert decision.needs_review is False

    def test_locked_en_autoswitch_off_keeps_en_on_es_detection(self) -> None:
        """Locked='en', det='es', autoswitch=False → stays 'en'.

        req: multilingual-014
        """
        decision = resolve_active_lang(
            _locked_session("en"),
            _det("es"),
            _cfg(lang_autoswitch=False),
        )
        assert decision.active_lang == "en"
        assert decision.switched is False

    def test_locked_session_same_lang_detection_keeps_active_lang(self) -> None:
        """Locked='es', det='es' → keeps 'es', resets any stale pending counters.

        req: multilingual-007 — keep active_lang while locked
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=1)
        decision = resolve_active_lang(session, _det("es"), _cfg(lang_autoswitch=True))

        assert decision.active_lang == "es"
        assert decision.switched is False
        # Same-lang detection should reset stale pending counters.
        assert decision.pending_switch_lang is None
        assert decision.pending_switch_count == 0

    def test_locked_es_unsupported_de_keeps_es_needs_review(self) -> None:
        """Locked='es', det='de' (unsupported) → keeps 'es', needs_review=True, reason logged.

        req: multilingual-008 — unsupported on locked session → keep + needs_review
        """
        decision = resolve_active_lang(
            _locked_session("es"),
            _det("de"),
            _cfg(),
        )

        assert decision.active_lang == "es"
        assert decision.needs_review is True
        assert decision.switched is False
        assert "unsupported-on-locked" in decision.reasons

    def test_locked_en_unsupported_fr_keeps_en_needs_review(self) -> None:
        """Locked='en', det='fr' (unsupported) → keeps 'en' + needs_review.

        req: multilingual-008
        """
        decision = resolve_active_lang(
            _locked_session("en"),
            _det("fr"),
            _cfg(),
        )
        assert decision.active_lang == "en"
        assert decision.needs_review is True
        assert "unsupported-on-locked" in decision.reasons

    def test_unsupported_on_locked_preserves_pending_counters(self) -> None:
        """Unsupported lang on locked session preserves existing pending_switch counters.

        req: multilingual-008 — counters unchanged when the detected lang is unsupported
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=1)
        decision = resolve_active_lang(session, _det("de"), _cfg())

        assert decision.pending_switch_lang == "pt"
        assert decision.pending_switch_count == 1

    def test_short_input_on_locked_session_no_switch(self) -> None:
        """Short/unreliable input (is_reliable=False) on locked session → no switch.

        req: multilingual-011 — short input → retain active_lang, do not trigger switch
        """
        session = _locked_session("es")
        det = _det("pt", is_reliable=False)  # short input
        decision = resolve_active_lang(
            session, det, _cfg(lang_autoswitch=True, autoswitch_min_turns=2)
        )

        assert decision.active_lang == "es"
        assert decision.switched is False

    def test_short_input_pending_counters_unchanged(self) -> None:
        """Short input on a session with a pending counter → counters stay the same.

        req: multilingual-011 — no counter increment on unreliable input
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=1)
        det = _det("pt", is_reliable=False)
        decision = resolve_active_lang(
            session, det, _cfg(lang_autoswitch=True, autoswitch_min_turns=2)
        )

        assert decision.pending_switch_lang == "pt"
        assert decision.pending_switch_count == 1
        assert decision.active_lang == "es"

    def test_short_input_autoswitch_on_still_no_switch(self) -> None:
        """Even with autoswitch enabled, unreliable input must not switch.

        req: multilingual-011 — is_reliable=False short-circuits before autoswitch logic
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=99)
        det = _det("pt", is_reliable=False)
        decision = resolve_active_lang(
            session, det, _cfg(lang_autoswitch=True, autoswitch_min_turns=2)
        )

        assert decision.switched is False
        assert decision.active_lang == "es"


# ===========================================================================
# (f) Autoswitch ON — consecutive-turn counter and switch firing
# req: multilingual-013
# ===========================================================================


class TestResolveActiveLangAutoSwitch:
    def test_autoswitch_on_first_pt_turn_accumulates_count(self) -> None:
        """Autoswitch ON, 1st consecutive 'pt' turn on 'es'-locked session → count=1, no switch.

        req: multilingual-013 — switch requires ≥ autoswitch_min_turns consecutive turns
        """
        session = _locked_session("es")  # no pending counter
        det = _det("pt")
        cfg = _cfg(lang_autoswitch=True, autoswitch_min_turns=2)

        decision = resolve_active_lang(session, det, cfg)

        assert decision.active_lang == "es"  # not switched yet
        assert decision.switched is False
        assert decision.pending_switch_lang == "pt"
        assert decision.pending_switch_count == 1

    def test_autoswitch_on_second_pt_turn_fires_switch(self) -> None:
        """Autoswitch ON, 2nd consecutive 'pt' turn → count reaches min_turns → switch fires.

        req: multilingual-013 — switch fires at autoswitch_min_turns (2)
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=1)
        det = _det("pt")
        cfg = _cfg(lang_autoswitch=True, autoswitch_min_turns=2)

        decision = resolve_active_lang(session, det, cfg)

        assert decision.active_lang == "pt"  # switched!
        assert decision.switched is True
        assert decision.first_turn is False
        assert decision.locked is True
        # Pending counters reset after the switch.
        assert decision.pending_switch_lang is None
        assert decision.pending_switch_count == 0

    def test_autoswitch_on_interrupted_counter_resets_to_new_candidate(self) -> None:
        """Autoswitch ON: pending 'pt' counter, then 'en' detected → reset counter to 'en', count=1.

        req: multilingual-013 — consecutive requirement: non-consecutive turns reset the counter
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=1)
        det = _det("en")
        cfg = _cfg(lang_autoswitch=True, autoswitch_min_turns=2)

        decision = resolve_active_lang(session, det, cfg)

        assert decision.active_lang == "es"  # not switched
        assert decision.switched is False
        assert decision.pending_switch_lang == "en"  # reset to new candidate
        assert decision.pending_switch_count == 1

    def test_autoswitch_off_does_not_switch_even_with_many_turns(self) -> None:
        """Autoswitch OFF: no switch regardless of how many consecutive turns in new language.

        req: multilingual-014 — hard lock when autoswitch is disabled
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=99)
        det = _det("pt")
        cfg = _cfg(lang_autoswitch=False)

        decision = resolve_active_lang(session, det, cfg)

        assert decision.active_lang == "es"
        assert decision.switched is False

    def test_autoswitch_on_min_turns_3_does_not_switch_at_turn_2(self) -> None:
        """Autoswitch ON with min_turns=3: count=2 is not enough to switch.

        req: multilingual-013 — switch only at ≥ autoswitch_min_turns, not before
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=1)
        det = _det("pt")
        cfg = _cfg(lang_autoswitch=True, autoswitch_min_turns=3)

        decision = resolve_active_lang(session, det, cfg)

        assert decision.active_lang == "es"
        assert decision.switched is False
        assert decision.pending_switch_count == 2  # accumulated, not fired

    def test_autoswitch_on_min_turns_3_fires_at_turn_3(self) -> None:
        """Autoswitch ON with min_turns=3: count=3 triggers the switch.

        req: multilingual-013
        """
        session = _locked_session("es", pending_switch_lang="pt", pending_switch_count=2)
        det = _det("pt")
        cfg = _cfg(lang_autoswitch=True, autoswitch_min_turns=3)

        decision = resolve_active_lang(session, det, cfg)

        assert decision.active_lang == "pt"
        assert decision.switched is True
