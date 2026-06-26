"""Single config source for the backend (pydantic-settings).

This is the ONE place model ids, supported languages, and secrets live; every other
module imports settings from here. Model ids are placeholders confirmed at integration.

Requirements: platform-scaffold-012 (single config module: model ids +
``supported=("es","en","pt")`` / ``fallback_lang="en"``), platform-scaffold-017
(fields correspond to the env vars listed in ``.env.example``).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Module-level language constants — the SINGLE source of truth.
# All other modules MUST import from here; never hardcode the tuple elsewhere.
# req: multilingual-003, platform-scaffold-012
# ---------------------------------------------------------------------------
SUPPORTED_LANGS: tuple[str, ...] = ("es", "en", "pt")
FALLBACK_LANG: str = "en"
LANG_DISPLAY_NAMES: dict[str, str] = {
    "es": "Spanish",
    "en": "English",
    "pt": "Portuguese",
}


class Settings(BaseSettings):
    """Application settings loaded from environment / ``.env``.

    Required fields have no default and must come from the environment; observability
    and geo tokens are optional and degrade to no-op when absent.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Required secrets (no default; sourced from env) ---
    # Only DATABASE_URL + ADMIN_TOKEN are required. All LLM traffic is routed through
    # the Pydantic AI Gateway (PYDANTIC_AI_GATEWAY_API_KEY). No direct-provider key
    # fields are defined here; this keeps migrations / ``get_settings()`` decoupled
    # from any LLM provider selection.
    database_url: str
    admin_token: str

    # --- Pydantic AI Gateway (single key routes all providers through logfire.pydantic.dev) ---
    # Obtained from logfire.pydantic.dev; key format: pylf_v1_<region>_<token>.
    # When set, use gateway/... model strings (see orchestrator_model / worker_model /
    # judge_model below). The gateway auto-injects traceparent for Logfire distributed
    # tracing and allows swapping providers without rotating individual API keys.
    pydantic_ai_gateway_api_key: str | None = None
    # Auto-inferred from the region encoded in the key; override only when using a
    # non-standard gateway deployment (e.g. self-hosted or staging).
    pydantic_ai_gateway_base_url: str | None = None

    # --- Optional tokens (None -> feature initializes in safe no-op mode) ---
    logfire_token: str | None = None
    posthog_key: str | None = None
    ipinfo_token: str | None = None

    # --- Model ids (PLACEHOLDERS; confirmed at integration time) ---
    # Default: gateway/... strings routed through the Pydantic AI Gateway (reads
    # PYDANTIC_AI_GATEWAY_API_KEY from env). The gateway is the ONLY LLM credential
    # path — no direct-provider keys are configured here. To swap provider/model,
    # override these vars in the environment (e.g. ORCHESTRATOR_MODEL=gateway/openai:gpt-4.1).
    orchestrator_model: str = "gateway/openai:gpt-4.1"
    worker_model: str = "gateway/openai:gpt-4.1-mini"
    judge_model: str = "gateway/openai:gpt-4.1-mini"

    # --- Language policy (consumed by later features) ---
    # req: multilingual-003 — supported language set and fallback
    supported: tuple[str, ...] = SUPPORTED_LANGS
    fallback_lang: str = FALLBACK_LANG
    # req: multilingual-011 — minimum detector confidence to trust a detection
    lang_confidence_min: float = 0.55
    # req: multilingual-011 — inputs shorter than this are too short to detect reliably
    min_input_chars: int = 12
    # req: multilingual-009 — consecutive turns required before auto-switch fires
    autoswitch_min_turns: int = 2
    # req: multilingual-009 — Tier-3 flag; default off keeps the hard session lock
    lang_autoswitch: bool = False

    # --- Evaluation runtime (req: evaluation-014, evaluation-018) ---
    # Tier-3 flag: when False, skips the end-of-conversation judge and the idle sweep.
    runtime_eval_enabled: bool = True
    # Seconds of inactivity after which a session is considered "ended" and eligible
    # for the idle-sweep grader.
    conversation_idle_timeout: int = 900

    # --- Guardrails (req: guardrails-015, guardrails-016) ---
    # Master kill-switch: when False, all guardrail checks are skipped and
    # guardrails.{input,output} are left empty (for debugging only).
    guardrails_enabled: bool = True
    # Tier-3 flag: when True, augments the deterministic core with an optional LLM
    # guardrail layer. Default off — the deterministic core is sufficient for production.
    guardrails_llm_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return the cached, process-wide :class:`Settings` instance.

    Lazy + cached so importing this module never instantiates ``Settings`` (which would
    fail when required env vars are absent, e.g. in static analysis / CI import checks).
    """
    return Settings()
