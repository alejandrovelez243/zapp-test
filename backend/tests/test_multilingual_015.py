"""Unit tests for multilingual-015 — language-switch offer instruction.

Verifies:
  (a) _lang_switch_instruction with pending_switch_lang="es", switched=False
      → instruction contains an offer to switch to Spanish, no "cannot change" claim.
  (b) _lang_switch_instruction with switched=True → instruction acknowledges the switch.
  (c) _lang_switch_instruction with no pending switch → returns empty string.
  (d) State machine switches active_lang after 2 consecutive turns in a new language
      with lang_autoswitch=True (the new default).

req: multilingual-013, multilingual-015
Design contract: specs/multilingual/design.md §2.3 / §2.4
"""

from __future__ import annotations

from app.agents.orchestrator import _lang_switch_instruction
from app.agents.session import ConversationSession
from app.config import Settings
from app.lang.detector import DetectionResult
from app.lang.state import ActiveLangDecision, resolve_active_lang

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**overrides: object) -> Settings:
    """Return a Settings instance with test-safe required fields + optional overrides."""
    return Settings(
        database_url="sqlite:///:memory:",
        admin_token="test-admin",
        **overrides,  # type: ignore[arg-type]
    )


def _locked_session(
    active_lang: str,
    *,
    pending_switch_lang: str | None = None,
    pending_switch_count: int = 0,
) -> ConversationSession:
    """Return a ConversationSession locked to *active_lang* with optional pending counters."""
    s = ConversationSession(id="ml-015-sess")
    s.active_lang = active_lang
    s.pending_switch_lang = pending_switch_lang
    s.pending_switch_count = pending_switch_count
    return s


def _det(lang: str, *, confidence: float = 0.92, is_reliable: bool = True) -> DetectionResult:
    """Convenience constructor for DetectionResult."""
    return DetectionResult(lang=lang, confidence=confidence, is_reliable=is_reliable)


# ===========================================================================
# (a) Offer instruction: pending_switch_lang set, switched=False
# req: multilingual-015
# ===========================================================================


class TestLangSwitchInstructionOffer:
    def test_offer_mentions_pending_language_spanish(self) -> None:
        """pending_switch_lang='es', switched=False → instruction offers to switch to Spanish.

        req: multilingual-015 — offer to continue in the user's detected language
        """
        decision = ActiveLangDecision(
            active_lang="en",
            first_turn=False,
            locked=True,
            switched=False,
            pending_switch_lang="es",
            pending_switch_count=1,
        )
        instruction = _lang_switch_instruction(decision, "English")

        assert "Spanish" in instruction, (
            f"Expected 'Spanish' in offer instruction; got: {instruction!r}"
        )

    def test_offer_contains_no_cannot_change_claim(self) -> None:
        """Offer instruction must NOT claim the system is unable to change language.

        req: multilingual-015 — system must NOT say it cannot switch
        """
        decision = ActiveLangDecision(
            active_lang="en",
            first_turn=False,
            locked=True,
            switched=False,
            pending_switch_lang="es",
            pending_switch_count=1,
        )
        instruction = _lang_switch_instruction(decision, "English")
        lower = instruction.lower()
        assert "cannot" not in lower, (
            f"Instruction must not claim inability to change language; got: {instruction!r}"
        )
        assert "unable" not in lower, f"Instruction must not say 'unable'; got: {instruction!r}"

    def test_offer_nonempty_when_pending(self) -> None:
        """Instruction is non-empty when a switch is pending.

        req: multilingual-015 — instruction must be emitted when switch is pending
        """
        decision = ActiveLangDecision(
            active_lang="en",
            first_turn=False,
            locked=True,
            switched=False,
            pending_switch_lang="pt",
            pending_switch_count=1,
        )
        instruction = _lang_switch_instruction(decision, "English")
        assert instruction, "Expected non-empty instruction when switch is pending"
        assert "Portuguese" in instruction

    def test_offer_includes_offer_keyword(self) -> None:
        """The offer instruction must encourage the model to OFFER the switch in the reply.

        req: multilingual-015 — model must offer, not hard-switch without asking
        """
        decision = ActiveLangDecision(
            active_lang="en",
            first_turn=False,
            locked=True,
            switched=False,
            pending_switch_lang="es",
            pending_switch_count=1,
        )
        instruction = _lang_switch_instruction(decision, "English")
        lower = instruction.lower()
        # At least one of these offer signals must appear.
        has_offer_signal = "offer" in lower or "would you like" in lower or "notice" in lower
        assert has_offer_signal, f"Expected offer language in instruction; got: {instruction!r}"


# ===========================================================================
# (b) Switch-completed instruction: switched=True
# req: multilingual-015
# ===========================================================================


class TestLangSwitchInstructionCompleted:
    def test_switch_completed_instruction_nonempty(self) -> None:
        """switched=True → instruction acknowledges the completed switch.

        req: multilingual-015 — acknowledge switch when it fires
        """
        decision = ActiveLangDecision(
            active_lang="es",
            first_turn=False,
            locked=True,
            switched=True,
            pending_switch_lang=None,
            pending_switch_count=0,
        )
        instruction = _lang_switch_instruction(decision, "Spanish")
        assert instruction, "Expected non-empty instruction when switch just fired"

    def test_switch_completed_instruction_mentions_new_language(self) -> None:
        """Switch acknowledgement mentions the new (now active) language name.

        req: multilingual-015 — model must know which language to acknowledge
        """
        decision = ActiveLangDecision(
            active_lang="pt",
            first_turn=False,
            locked=True,
            switched=True,
            pending_switch_lang=None,
            pending_switch_count=0,
        )
        instruction = _lang_switch_instruction(decision, "Portuguese")
        assert "Portuguese" in instruction, (
            f"Expected 'Portuguese' in switch-acknowledgement; got: {instruction!r}"
        )


# ===========================================================================
# (c) No-op: no pending switch, no switch event
# ===========================================================================


class TestLangSwitchInstructionNoop:
    def test_no_switch_event_returns_empty_string(self) -> None:
        """No pending switch and no fired switch → helper returns empty string.

        req: multilingual-015 — no extraneous instruction when not in a switch scenario
        """
        decision = ActiveLangDecision(
            active_lang="en",
            first_turn=True,
            locked=True,
            switched=False,
            pending_switch_lang=None,
            pending_switch_count=0,
        )
        instruction = _lang_switch_instruction(decision, "English")
        assert instruction == "", f"Expected empty string; got: {instruction!r}"


# ===========================================================================
# (d) State machine: switch fires after 2 consecutive turns with default autoswitch=True
# req: multilingual-013, multilingual-015
# ===========================================================================


class TestAutoswitchDefaultOn:
    def test_switch_fires_after_two_consecutive_turns_default_cfg(self) -> None:
        """Default config (lang_autoswitch=True now default) fires switch after 2 turns.

        req: multilingual-013 — switch at autoswitch_min_turns
        req: multilingual-015 — default autoswitch=True means the counter path is live
        """
        cfg = _cfg()  # lang_autoswitch=True by default
        session = _locked_session("en", pending_switch_lang="es", pending_switch_count=1)

        decision = resolve_active_lang(session, _det("es"), cfg)

        assert decision.active_lang == "es", (
            f"Expected active_lang='es' after 2 consecutive ES turns; got {decision.active_lang!r}"
        )
        assert decision.switched is True
        assert decision.pending_switch_lang is None
        assert decision.pending_switch_count == 0

    def test_first_es_turn_accumulates_count_with_default_cfg(self) -> None:
        """First consecutive ES turn on EN-locked session → counter increments (default=True).

        req: multilingual-013, multilingual-015
        """
        cfg = _cfg()  # lang_autoswitch=True by default
        session = _locked_session("en")

        decision = resolve_active_lang(session, _det("es"), cfg)

        assert decision.active_lang == "en"  # not switched yet
        assert decision.switched is False
        assert decision.pending_switch_lang == "es"
        assert decision.pending_switch_count == 1

    def test_hard_lock_still_works_when_explicitly_disabled(self) -> None:
        """Explicitly setting lang_autoswitch=False still enforces the hard lock.

        req: multilingual-014 — hard lock path must remain available via config
        """
        cfg = _cfg(lang_autoswitch=False)
        session = _locked_session("en", pending_switch_lang="es", pending_switch_count=99)

        decision = resolve_active_lang(session, _det("es"), cfg)

        assert decision.active_lang == "en"
        assert decision.switched is False
