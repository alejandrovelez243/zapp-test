"""Deterministic, multilingual (ES/EN/PT) guardrail detectors.

All detector methods are **pure** — they never raise (return ``False``/``[]`` on any
internal error so the engine's fail-safe path (guardrails-019) remains the sole place
that turns a detector exception into a block).  Pattern sets cover ES, EN, and PT per
guardrails-011.  The optional LLM layer (``guardrails_llm_enabled``) refines these
deterministic signals; it is NOT wired here.

The :class:`Detectors` class compiles every regex pattern **once** in ``__init__`` and
holds them as instance state, so the compile cost is paid only at construction time —
not on every detection call.

Requirements:
  guardrails-003 — detect_prompt_injection (injection → block)
  guardrails-004 — detect_jailbreak (jailbreak → block)
  guardrails-005 — detect_toxicity (toxicity → block)
  guardrails-006 — detect_pii + redact_pii (PII → redact + continue)
  guardrails-007 — detect_off_topic (off-topic → soft flag)
  guardrails-008 — detect_pii reused on output (pii_leak → redact)
  guardrails-009 — detect_toxicity reused on output (toxicity → block)
  guardrails-010 — detect_secret_leak (secret_leak → block)
  guardrails-011 — ES/EN/PT patterns throughout
  guardrails-014 — deterministic, pattern/rule-based; reproducible across runs

Design: specs/guardrails/design.md §2.1 + §4
"""

from __future__ import annotations

import contextlib
import re

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "Detectors",
    "PiiMatch",
]


# ---------------------------------------------------------------------------
# Data model — §4 of the design
# ---------------------------------------------------------------------------


class PiiMatch(BaseModel):
    """A single PII span detected in the input text.

    kind:  one of ``email`` | ``phone`` | ``national_id`` | ``card``
    start: start character offset in the original text (inclusive)
    end:   end character offset in the original text (exclusive)

    req: guardrails-006
    """

    model_config = ConfigDict(frozen=True)

    kind: str  # email | phone | national_id | card
    start: int
    end: int


# ---------------------------------------------------------------------------
# Detectors class — compile patterns once; expose methods
# ---------------------------------------------------------------------------


class Detectors:
    """Compiled guardrail detectors for ES / EN / PT.

    Instantiate once (e.g. per-process or injected into
    :class:`~app.guardrails.engine.GuardrailEngine`) and reuse the instance across
    turns.  All regex patterns are compiled in ``__init__`` so subsequent method calls
    are fast.

    req: guardrails-003, guardrails-004, guardrails-005, guardrails-006, guardrails-007,
         guardrails-008, guardrails-009, guardrails-010, guardrails-011, guardrails-014
    """

    def __init__(self) -> None:
        # ------------------------------------------------------------------ #
        # § PII — email / phone / national-id / card (guardrails-006/008)
        # ------------------------------------------------------------------ #

        self._email_re: re.Pattern[str] = re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
        )

        self._phone_re: re.Pattern[str] = re.compile(
            r"(?:"
            # International with '+': +34 612 345 678 / +1-555-867-5309
            r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
            r"|"
            # NANP with parentheses: (555) 867-5309
            r"\(\d{3}\)[\s\-.]?\d{3}[\s\-.]?\d{4}"
            r"|"
            # NANP with separators only (no parens): 555-867-5309 / 555.867.5309
            r"\b\d{3}[\-\.]\d{3}[\-\.]\d{4}\b"
            r")"
        )

        self._national_id_re: re.Pattern[str] = re.compile(
            r"(?:"
            # US SSN: 123-45-6789 or 123 45 6789
            r"\b\d{3}[\-\s]\d{2}[\-\s]\d{4}\b"
            r"|"
            # ES DNI: 8 digits + 1 check letter (e.g. 12345678Z)
            r"\b\d{8}[A-Za-z]\b"
            r"|"
            # ES NIE: X/Y/Z + 7 digits + letter (e.g. X1234567L)
            r"\b[XYZxyz]\d{7}[A-Za-z]\b"
            r"|"
            # BR CPF: 000.000.000-00
            r"\b\d{3}\.\d{3}\.\d{3}[-]\d{2}\b"
            r")"
        )

        # Credit card — major networks with optional space/hyphen separators.
        self._card_re: re.Pattern[str] = re.compile(
            r"\b(?:"
            # Visa (16 digits starting with 4)
            r"4\d{3}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
            r"|"
            # Mastercard (16 digits, 5[1-5]xx)
            r"5[1-5]\d{2}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
            r"|"
            # Amex (15 digits, 3[47]xx)
            r"3[47]\d{2}[\s\-]?\d{6}[\s\-]?\d{5}"
            r"|"
            # Discover (16 digits, 6011)
            r"6011[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
            r")\b"
        )

        self._pii_kinds: list[tuple[re.Pattern[str], str]] = [
            (self._email_re, "email"),
            (self._phone_re, "phone"),
            (self._national_id_re, "national_id"),
            (self._card_re, "card"),
        ]

        # ------------------------------------------------------------------ #
        # § Prompt injection (guardrails-003) — EN / ES / PT
        # ------------------------------------------------------------------ #

        _injection_patterns: list[str] = [
            # ---- English ----
            r"ignore\s+(?:previous|prior|all|the)\s+(?:instructions?|prompts?|directives?|constraints?)",
            r"disregard\s+(?:previous|prior|all|the)\s+(?:instructions?|prompts?|directives?|constraints?)",
            r"forget\s+(?:your|all|the|previous)\s+(?:instructions?|prompts?|rules?|constraints?)",
            r"override\s+(?:your|the|previous|prior)\s+(?:instructions?|prompts?|rules?|constraints?)",
            r"(?:reveal|print|show|output|display)\s+(?:your|the|my)\s+"
            r"(?:system\s+)?(?:prompt|instructions?|rules?|context)",
            r"system\s*prompt",
            r"you\s+are\s+now\s+(?:a|an|the)\b",
            r"from\s+now\s+on\s+(?:you\s+are|act\s+as)\b",
            r"new\s+(?:persona|character|role|identity)",
            r"ignore\s+all\s+previous",
            r"do\s+not\s+follow\s+(?:your|the)\s+(?:instructions?|rules?|guidelines?)",
            # ---- Spanish ----
            r"olvida\s+(?:las?\s+)?(?:instrucciones?|reglas?|restricciones?|todo\s+lo\s+anterior)",
            r"ignora\s+(?:las?\s+)?(?:instrucciones?|reglas?|restricciones?|todo\s+lo\s+anterior)",
            r"instrucciones?\s+(?:previas?|anteriores?)",
            r"(?:revela|muestra|imprime|muéstrame)\s+(?:el\s+)?(?:system\s+prompt|instrucciones?|prompt)",
            r"ahora\s+eres\b",
            r"actúa\s+como\s+si\s+(?:eres|fueras|no\s+tuvieras)",
            r"nueva\s+(?:persona|identidad|personalidad)",
            r"desde\s+ahora\s+(?:eres|actúa\s+como)\b",
            r"no\s+sigas\s+(?:las?\s+)?(?:instrucciones?|reglas?)",
            # ---- Portuguese ----
            r"ignore?\s+as\s+instru[cç][õo]es",
            r"esqueça\s+as\s+instru[cç][õo]es",
            r"você\s+agora\s+é\b",
            r"(?:revela|mostre|imprima)\s+(?:o\s+)?(?:system\s+prompt|instru[cç][õo]es)",
            r"nova\s+(?:persona|identidade|personalidade)",
            r"a\s+partir\s+de\s+agora\s+(?:você\s+é|aja\s+como)\b",
            r"não\s+siga\s+as\s+instru[cç][õo]es",
        ]

        self._injection_re: re.Pattern[str] = re.compile(
            r"(?:" + r"|".join(_injection_patterns) + r")",
            re.IGNORECASE | re.UNICODE,
        )

        # ------------------------------------------------------------------ #
        # § Jailbreak (guardrails-004) — EN / ES / PT
        # ------------------------------------------------------------------ #

        _jailbreak_patterns: list[str] = [
            # ---- English ----
            r"pretend\s+you\s+have\s+no\s+(?:rules|restrictions|guidelines|ethics)",
            r"act\s+as\s+if\s+you\s+have\s+no\s+(?:rules|restrictions|guidelines|ethics)",
            r"do\s+anything\s+now",
            r"\bjailbreak\b",
            r"without\s+(?:any\s+)?(?:ethical\s+)?(?:restrictions?|guidelines?|rules?|limits?|constraints?)",
            r"no\s+(?:ethical\s+)?(?:guidelines?|restrictions?|rules?|limits?)",
            r"ignore\s+(?:your|all|the)\s+ethics",
            r"bypass\s+(?:your\s+)?(?:restrictions?|safety|guidelines?|filters?)",
            r"you\s+have\s+no\s+(?:rules|restrictions|limitations|guidelines|ethics)",
            r"developer\s+mode",
            r"(?:evil|opposite|uncensored|unrestricted)\s+(?:mode|version|ai|model|twin|persona)",
            r"you\s+are\s+free\s+from\s+(?:restrictions?|guidelines?|rules?|limitations?)",
            r"override\s+(?:safety|ethical|content)\s+(?:filters?|guidelines?|restrictions?)",
            r"(?:gran|god)\s+mode",
            # ---- Spanish ----
            r"actúa?\s+sin\s+restricciones",
            r"actúa?\s+como\s+si\s+no\s+tuvieras?\s+(?:reglas?|restricciones?|ética)",
            r"eres\s+una?\s+(?:IA|inteligencia\s+artificial)\s+sin\s+restricciones",
            r"sin\s+restricciones\s+(?:éticas?|morales?)",
            r"ignora\s+tu\s+(?:ética|moral|restricciones?)",
            r"pretende\s+que\s+no\s+tienes?\s+(?:reglas?|restricciones?)",
            r"modo\s+(?:desarrollador|sin\s+restricciones|maligno)",
            # ---- Portuguese ----
            r"finja\s+que\s+não\s+tem\s+(?:regras?|restrições|ética)",
            r"aja\s+sem\s+restrições",
            r"você\s+não\s+tem\s+(?:regras?|restrições|limitações)",
            r"sem\s+restrições\s+(?:éticas?|morais?)",
            r"ignore?\s+(?:suas?\s+)?(?:restrições|ética|regras?)",
            r"modo\s+(?:desenvolvedor|sem\s+restrições|maligno)",
            r"faça\s+de\s+conta\s+que\s+(?:é\s+uma?\s+(?:IA|inteligência\s+artificial)\s+sem|não\s+tem)",
        ]

        self._jailbreak_re: re.Pattern[str] = re.compile(
            r"(?:" + r"|".join(_jailbreak_patterns) + r")",
            re.IGNORECASE | re.UNICODE,
        )

        # ------------------------------------------------------------------ #
        # § Toxicity (guardrails-005/009) — per-language patterns
        # ------------------------------------------------------------------ #
        # Curated for a philosophy-school context: explicit threats of violence,
        # extreme profanity, and hate-speech structures.  Keep lists small but
        # representative; the optional LLM layer (guardrails_llm_enabled) refines.
        # Word-boundary (\b) matching limits false positives on partial matches.

        _toxicity_en: re.Pattern[str] = re.compile(
            r"(?:"
            # Explicit threats of violence
            r"(?:i(?:'ll|\s+will)|i(?:'m|\s+am)\s+going\s+to)\s+(?:kill|murder|harm|hurt)\s+(?:you|him|her|them|everyone)"
            r"|(?:death|bomb)\s+threat"
            r"|\bkill\s+yourself\b"
            r"|\bgo\s+kill\s+yourself\b"
            # Extreme directed profanity
            r"|\bf+u+c+k\s+(?:you|off|this)\b"
            r"|\bpiece\s+of\s+s+h+[i1]+t\b"
            # Hate-speech structures (group-targeting violence/extermination language)
            r"|\b(?:kill|exterminate|gas|wipe\s+out)\s+(?:all\s+)?(?:the\s+)?"
            r"(?:jews?|muslims?|blacks?|whites?|gays?|lesbians?|immigrants?)\b"
            r"|\bhate\s+all\s+(?:jews?|muslims?|blacks?|whites?|gays?|lesbians?)\b"
            r")",
            re.IGNORECASE,
        )

        _toxicity_es: re.Pattern[str] = re.compile(
            r"(?:"
            # Amenazas explícitas
            r"te\s+voy\s+a\s+(?:matar|matar|golpear|hacer\s+daño)"
            r"|voy\s+a\s+(?:matarte|asesinarte|hacerte\s+daño)"
            r"|te\s+mato\b"
            # Insultos graves / hate speech
            r"|hijo\s+de\s+(?:la\s+gran\s+)?puta"
            r"|vete\s+(?:a\s+la\s+)?(?:mierda|chingada)"
            r"|\b(?:matar|exterminar|eliminar)\s+(?:a\s+todos?\s+los?\s+)?"
            r"(?:judíos?|musulmanes?|negros?|gays?|inmigrantes?)\b"
            r"|\bodio\s+a\s+(?:todos?\s+los?\s+)?(?:judíos?|musulmanes?|negros?|gays?)\b"
            r")",
            re.IGNORECASE | re.UNICODE,
        )

        _toxicity_pt: re.Pattern[str] = re.compile(
            r"(?:"
            # Ameaças explícitas
            r"vou\s+te\s+(?:matar|machucar|bater)"
            r"|vou\s+(?:matar|assassinar|machucar)\s+(?:você|te)\b"
            r"|te\s+mato\b"
            # Insultos graves / hate speech
            r"|filho\s+da\s+(?:puta|mãe)"
            r"|vai\s+(?:se\s+)?(?:foder|tomar\s+no\s+cu)"
            r"|\b(?:matar|exterminar|eliminar)\s+(?:todos?\s+os?\s+)?"
            r"(?:judeus?|muçulmanos?|negros?|gays?|imigrantes?)\b"
            r"|\bodeio\s+(?:todos?\s+os?\s+)?(?:judeus?|muçulmanos?|negros?|gays?)\b"
            r")",
            re.IGNORECASE | re.UNICODE,
        )

        self._toxicity_map: dict[str, re.Pattern[str]] = {
            "en": _toxicity_en,
            "es": _toxicity_es,
            "pt": _toxicity_pt,
        }

        # ------------------------------------------------------------------ #
        # § Off-topic (guardrails-007) — soft heuristic, EN / ES / PT
        # ------------------------------------------------------------------ #
        # Best-effort only; this is a flag (not a block) by design.  Covers medical,
        # legal, financial-advice, and political-opinion keywords.  The LLM layer
        # refines when guardrails_llm_enabled is set.

        _off_topic_en_parts: list[str] = [
            # Medical advice
            r"medical\s+advice",
            r"diagnos(?:e|is|tic)",
            r"prescri(?:be|ption)",
            r"should\s+i\s+take\s+(?:this\s+)?(?:medication|medicine|pill|drug)",
            r"what\s+medication\s+(?:should|do\s+i)",
            r"treatment\s+for\b",
            r"cure\s+for\b",
            r"chemotherapy|radiation\s+therapy",
            # Legal advice
            r"legal\s+advice",
            r"\blawsuit\b",
            r"\battorney\b",
            r"should\s+i\s+sue",
            r"criminal\s+charges?",
            r"legal\s+representation",
            # Financial advice
            r"stock\s+tips?",
            r"investment\s+advice",
            r"buy\s+(?:stocks?|shares?|bitcoin|crypto(?:currency)?)",
            r"trading\s+signals?",
            r"\bforex\b",
            r"make\s+money\s+fast",
            r"financial\s+advice",
            # Political opinion
            r"vote\s+for\b",
            r"who\s+(?:should\s+i\s+vote|to\s+vote\s+for)",
            r"political\s+party",
            r"election\s+results?",
            r"\brepublican\b",
            r"\bdemocrat\b",
        ]

        _off_topic_es_parts: list[str] = [
            # Consejo médico
            r"consejo\s+médico",
            r"diagnóstico",
            r"receta\s+médica",
            r"debo\s+tomar\s+(?:este?\s+)?(?:medicamento|pastilla|medicina)",
            r"tratamiento\s+(?:para|del?)\b",
            r"cura\s+(?:para|del?)\b",
            r"quimioterapia",
            # Consejo legal
            r"asesoramiento\s+legal",
            r"demanda\s+judicial",
            r"\babogado\b",
            r"debo\s+demandar",
            r"cargos\s+(?:penales|criminales?)",
            # Consejo financiero
            r"consejos?\s+(?:de\s+)?inversión",
            r"comprar\s+acciones?",
            r"\bcriptomoneda\b",
            r"señales?\s+de\s+trading",
            r"\bforex\b",
            r"ganar\s+dinero\s+rápido",
            r"asesoramiento\s+financiero",
            # Político
            r"votar\s+(?:por|a)\b",
            r"a\s+quién\s+(?:voto|votar)",
            r"partido\s+político",
            r"resultados?\s+electorales?",
        ]

        _off_topic_pt_parts: list[str] = [
            # Conselho médico
            r"conselho\s+médico",
            r"diagnóstico",
            r"receita\s+médica",
            r"devo\s+tomar\s+(?:este?\s+)?(?:medicamento|comprimido|remédio)",
            r"tratamento\s+(?:para|do?)\b",
            r"cura\s+(?:para|do?)\b",
            r"quimioterapia",
            # Conselho jurídico
            r"assessoria\s+jurídica",
            r"processo\s+judicial",
            r"\badvogado\b",
            r"devo\s+processar",
            r"acusações?\s+(?:criminais?|penais?)",
            # Conselho financeiro
            r"dicas?\s+(?:de\s+)?investimento",
            r"comprar\s+ações?",
            r"\bcriptomoeda\b",
            r"sinais?\s+de\s+trading",
            r"\bforex\b",
            r"ganhar\s+dinheiro\s+rápido",
            r"assessoria\s+financeira",
            # Político
            r"votar\s+(?:em|por)\b",
            r"em\s+quem\s+(?:voto|votar)",
            r"partido\s+político",
            r"resultados?\s+eleitorais?",
        ]

        self._off_topic_re: re.Pattern[str] = re.compile(
            r"\b(?:"
            + r"|".join(_off_topic_en_parts + _off_topic_es_parts + _off_topic_pt_parts)
            + r")\b",
            re.IGNORECASE | re.UNICODE,
        )

        # ------------------------------------------------------------------ #
        # § Secret leak (guardrails-010) — API key shapes / prompt fragments
        # ------------------------------------------------------------------ #

        self._api_key_re: re.Pattern[str] = re.compile(
            r"(?:"
            # OpenAI-style key
            r"sk-[A-Za-z0-9]{20,}"
            r"|"
            # Pydantic AI Gateway key (pylf_v<int>_<region>_<token>)
            r"pylf_v\d+_[A-Za-z0-9_]+"
            r")"
        )

        # Patterns that strongly suggest the model is revealing its system prompt or
        # internal instructions in a reply — output-side guard.
        self._prompt_fragment_re: re.Pattern[str] = re.compile(
            r"(?:"
            r"(?:my|your|the)\s+(?:system\s+)?(?:instructions?\s+(?:are|say|tell\s+me)|prompt\s+(?:is|says))\s*:"
            r"|you\s+are\s+(?:zapp|a\s+philosophy\s+school\s+assistant)"
            r"|i\s+(?:am|was)\s+(?:instructed|told|programmed)\s+to\b"
            r"|(?:my|the)\s+context\s+(?:is|window\s+(?:is|contains))\s*:"
            r"|(?:begin|start)\s+of\s+system\s+prompt"
            r")",
            re.IGNORECASE,
        )

    # ---------------------------------------------------------------------- #
    # § PII detection — email / phone / national-id / card (guardrails-006/008)
    # ---------------------------------------------------------------------- #

    def detect_pii(self, text: str) -> list[PiiMatch]:
        """Return all PII spans in *text* (email, phone, national_id, card).

        Spans may overlap — callers should pass the full list to :meth:`redact_pii`,
        which resolves overlaps via a left-to-right first-wins strategy.

        Never raises; returns ``[]`` on any internal error.

        req: guardrails-006, guardrails-011, guardrails-014
        """
        try:
            matches: list[PiiMatch] = []
            for pattern, kind in self._pii_kinds:
                for mo in pattern.finditer(text):
                    matches.append(PiiMatch(kind=kind, start=mo.start(), end=mo.end()))
            return matches
        except Exception:
            return []

    def redact_pii(self, text: str, matches: list[PiiMatch]) -> str:
        """Return *text* with every :class:`PiiMatch` span replaced by ``[REDACTED_<KIND>]``.

        Overlapping spans are resolved left-to-right (first-wins); later spans whose
        ``start`` falls inside the current cursor are skipped silently.

        Never raises; returns the original *text* on any internal error.

        req: guardrails-006, guardrails-008
        """
        if not matches:
            return text
        try:
            sorted_spans = sorted(matches, key=lambda m: m.start)
            parts: list[str] = []
            cursor: int = 0
            for span in sorted_spans:
                if span.start < cursor:
                    continue  # overlapping — skip
                parts.append(text[cursor : span.start])
                parts.append(f"[REDACTED_{span.kind.upper()}]")
                cursor = span.end
            parts.append(text[cursor:])
            return "".join(parts)
        except Exception:
            return text

    # ---------------------------------------------------------------------- #
    # § Prompt injection (guardrails-003) — EN / ES / PT
    # ---------------------------------------------------------------------- #

    def detect_prompt_injection(self, text: str) -> bool:
        """Return ``True`` if *text* appears to contain a prompt-injection attempt.

        Covers EN / ES / PT patterns.  Never raises; returns ``False`` on any error.

        req: guardrails-003, guardrails-011, guardrails-014
        """
        try:
            return bool(self._injection_re.search(text))
        except Exception:
            return False

    # ---------------------------------------------------------------------- #
    # § Jailbreak (guardrails-004) — EN / ES / PT
    # ---------------------------------------------------------------------- #

    def detect_jailbreak(self, text: str) -> bool:
        """Return ``True`` if *text* contains a jailbreak attempt.

        Covers EN / ES / PT patterns (roleplay-bypass, DAN variants, restriction-removal).
        Never raises; returns ``False`` on any error.

        req: guardrails-004, guardrails-011, guardrails-014
        """
        try:
            return bool(self._jailbreak_re.search(text))
        except Exception:
            return False

    # ---------------------------------------------------------------------- #
    # § Toxicity (guardrails-005/009) — per-language wordlists/patterns
    # ---------------------------------------------------------------------- #

    def detect_toxicity(self, text: str, lang: str) -> bool:
        """Return ``True`` if *text* contains toxic or abusive content for *lang*.

        Selects the per-language pattern set (EN/ES/PT); falls back to EN for
        unknown language codes.  Never raises; returns ``False`` on any error.

        req: guardrails-005, guardrails-009, guardrails-011, guardrails-014
        """
        try:
            pattern: re.Pattern[str] = self._toxicity_map.get(
                lang.lower(), self._toxicity_map["en"]
            )
            return bool(pattern.search(text))
        except Exception:
            return False

    # ---------------------------------------------------------------------- #
    # § Off-topic (guardrails-007) — soft heuristic, EN / ES / PT
    # ---------------------------------------------------------------------- #

    def detect_off_topic(self, text: str) -> bool:
        """Return ``True`` if *text* appears clearly out-of-domain (soft heuristic).

        Covers medical-advice, legal-advice, financial-advice, and political-opinion
        keywords across EN / ES / PT.  This is a **soft flag only** — it never directly
        causes a block; the engine maps it to the ``flag`` action.

        Never raises; returns ``False`` on any error.

        req: guardrails-007, guardrails-011, guardrails-014
        """
        try:
            return bool(self._off_topic_re.search(text))
        except Exception:
            return False

    # ---------------------------------------------------------------------- #
    # § Secret leak (guardrails-010) — admin token / API key shapes / prompt fragments
    # ---------------------------------------------------------------------- #

    def detect_secret_leak(self, text: str) -> bool:
        """Return ``True`` if *text* contains an admin token, API key, or system-prompt fragment.

        Checks (in order):
        1. The ``admin_token`` VALUE from :func:`app.config.get_settings` — loaded lazily
           so that test environments without ``DATABASE_URL`` do not crash on import.
        2. API key shapes: ``sk-[A-Za-z0-9]{20,}`` and ``pylf_v<N>_...``.
        3. Obvious system-prompt fragment patterns.

        Never raises; returns ``False`` on any internal error (settings unavailable, etc.).

        req: guardrails-010, guardrails-014
        """
        try:
            # 1. Admin token value — lazy import avoids import-time settings failure
            with contextlib.suppress(Exception):
                from app.config import get_settings

                admin_token: str = get_settings().admin_token
                if admin_token and admin_token in text:
                    return True

            # 2. API key shapes
            if self._api_key_re.search(text):
                return True

            # 3. System-prompt fragments
            return bool(self._prompt_fragment_re.search(text))
        except Exception:
            return False
