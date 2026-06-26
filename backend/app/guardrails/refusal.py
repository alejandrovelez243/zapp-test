"""Safe refusal messages for blocked guardrail turns.

Implements ``safe_refusal(active_lang, category) -> str`` (§2.3 of the guardrails design).
The returned string is written in ``active_lang`` (ES/EN/PT; falls back to EN for anything
else), tailored by ``category``, and never echoes the offending content.

Requirements:
  guardrails-011 — guardrails operate across ES, EN, and PT; a blocked turn's refusal is
                   written in the session's ``active_lang``.
  guardrails-012 — WHEN a guardrail blocks a turn THE SYSTEM SHALL still emit the full
                   nine-field ``TurnOutput`` with the safe refusal as ``reply`` (never a
                   500, never the raw blocked content).
"""

# ---------------------------------------------------------------------------
# Category name constants — MUST match the eval adversarial ``must_trip`` labels
# (guardrails-017) and the names emitted by engine.GuardrailResult.triggered.
# ---------------------------------------------------------------------------
PROMPT_INJECTION: str = "prompt_injection"
JAILBREAK: str = "jailbreak"
TOXICITY: str = "toxicity"
SECRET_LEAK: str = "secret_leak"

# Supported active languages (ES/EN/PT per the per-turn contract).
# Any other code is silently treated as the fallback.
_FALLBACK_LANG: str = "en"

# Internal sentinel key for the catch-all / generic default message.
_DEFAULT_KEY: str = "_default"

# ---------------------------------------------------------------------------
# Refusal strings — per lang, per category.
# Authoring rules (non-negotiable):
#   1. Written entirely in the target language.
#   2. Never contain or echo any user-supplied content.
#   3. Short + on-brand for a philosophy-school assistant.
#   4. Neutral — they clarify rather than accuse.
# ---------------------------------------------------------------------------
_REFUSALS: dict[str, dict[str, str]] = {
    # --- Spanish -------------------------------------------------------
    "es": {
        # guardrails-003: prompt injection → block
        PROMPT_INJECTION: (
            "Lo siento, no puedo ayudarte con eso. "
            "¿Tienes alguna pregunta sobre filosofía o los cursos de Zapp?"
        ),
        # guardrails-004: jailbreak → block
        JAILBREAK: (
            "Lo siento, no puedo ayudarte con eso. "
            "¿Tienes alguna pregunta sobre filosofía o los cursos de Zapp?"
        ),
        # guardrails-005: toxicity → block (neutral de-escalation)
        TOXICITY: (
            "Prefiero mantener nuestra conversación en un tono respetuoso. "
            "¿En qué más puedo ayudarte con Zapp?"
        ),
        # guardrails-010: secret leak in output → block
        SECRET_LEAK: (
            "No puedo compartir esa información. "
            "¿Puedo ayudarte con algo relacionado con nuestros cursos?"
        ),
        # catch-all for unknown categories
        _DEFAULT_KEY: (
            "No puedo ayudarte con eso en este momento. "
            "¿Tienes alguna pregunta sobre Zapp o filosofía?"
        ),
    },
    # --- English -------------------------------------------------------
    "en": {
        # guardrails-003
        PROMPT_INJECTION: (
            "I'm sorry, I can't help with that. "
            "Do you have a question about philosophy or Zapp courses?"
        ),
        # guardrails-004
        JAILBREAK: (
            "I'm sorry, I can't help with that. "
            "Do you have a question about philosophy or Zapp courses?"
        ),
        # guardrails-005
        TOXICITY: (
            "I'd prefer to keep our conversation respectful. How else can I help you with Zapp?"
        ),
        # guardrails-010
        SECRET_LEAK: (
            "I'm not able to share that information. "
            "Can I help you with something related to our courses?"
        ),
        _DEFAULT_KEY: (
            "I can't help with that right now. Do you have a question about Zapp or philosophy?"
        ),
    },
    # --- Portuguese ----------------------------------------------------
    "pt": {
        # guardrails-003
        PROMPT_INJECTION: (
            "Lamento, não consigo ajudar com isso. "
            "Tem alguma pergunta sobre filosofia ou os cursos da Zapp?"
        ),
        # guardrails-004
        JAILBREAK: (
            "Lamento, não consigo ajudar com isso. "
            "Tem alguma pergunta sobre filosofia ou os cursos da Zapp?"
        ),
        # guardrails-005
        TOXICITY: (
            "Prefiro manter a nossa conversa num tom respeitoso. "
            "Em que mais posso ajudá-lo com a Zapp?"
        ),
        # guardrails-010
        SECRET_LEAK: (
            "Não posso partilhar essa informação. "
            "Posso ajudá-lo com algo relacionado com os nossos cursos?"
        ),
        _DEFAULT_KEY: (
            "Não consigo ajudar com isso neste momento. "
            "Tem alguma pergunta sobre a Zapp ou filosofia?"
        ),
    },
}


def safe_refusal(active_lang: str, category: str) -> str:
    """Return a neutral, brief refusal string in ``active_lang`` for ``category``.

    The message is on-brand for a philosophy-school assistant: polite, short, and always
    redirects the student to a legitimate use case.  It contains no reference to the
    user's original message and never echoes offending content.

    Args:
        active_lang: ISO 639-1 code of the session's active language (``"es"``,
            ``"en"``, or ``"pt"``).  Any unsupported code silently falls back to
            ``"en"`` so the turn always completes (guardrails-012).
        category: The guardrail category that fired.  Recognised values are
            ``"prompt_injection"``, ``"jailbreak"``, ``"toxicity"``, and
            ``"secret_leak"``.  Any unrecognised string returns the generic
            default message for ``active_lang`` (guardrails-011).

    Returns:
        A short, on-brand philosophy-school refusal written in ``active_lang``.

    Requirements satisfied: guardrails-011, guardrails-012.
    """
    # Normalise the lang code; fall back to EN for unsupported languages.
    lang_map: dict[str, str] = _REFUSALS.get(active_lang.lower(), _REFUSALS[_FALLBACK_LANG])
    return lang_map.get(category, lang_map[_DEFAULT_KEY])
