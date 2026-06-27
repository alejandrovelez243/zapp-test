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
    # req: multilingual-009, multilingual-015 — default on; after autoswitch_min_turns
    # consecutive turns in a different supported language the system offers / fires a switch.
    # Set LANG_AUTOSWITCH=false in env to revert to the hard session lock (multilingual-014).
    lang_autoswitch: bool = True

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

    # --- Geo / Signal-Fusion (req: orchestrator-and-fusion-015, orchestrator-and-fusion-016) ---
    # When False, the geo-IP call is skipped entirely and detected_country is set to null
    # without error (useful in offline/dev environments).
    # req: orchestrator-and-fusion-015
    geo_fusion_enabled: bool = True
    # When False, the REST Countries locale-enrichment call is skipped; the service falls
    # back to default_locale / default_timezone for the detected country.
    # req: orchestrator-and-fusion-016
    rest_countries_enabled: bool = True
    # Base URL for the ipapi.co geo-IP API (keyless).
    ipapi_base_url: str = "https://ipapi.co"
    # Base URL for the REST Countries v3.1 API.
    rest_countries_base_url: str = "https://restcountries.com/v3.1"
    # HTTP timeout (seconds) applied to every outbound geo / locale enrichment call.
    geo_timeout: float = 3.0
    # Locale applied when REST Countries enrichment is skipped or fails.
    default_locale: str = "en-US"
    # Timezone applied when REST Countries enrichment is skipped or fails.
    default_timezone: str = "UTC"

    # --- FAQ-RAG (req: faq-rag-005, faq-rag-009, faq-rag-016) ---
    # Tier-3 flag: when False (default) retrieval uses cosine-only (pgvector HNSW);
    # when True, also adds a keyword score (Postgres ILIKE / ts_rank) before ranking.
    # req: faq-rag-016
    hybrid_retrieval: bool = False

    # Maximum number of chunks returned by the cosine retrieval query.
    # req: faq-rag-009
    rag_top_k: int = 5

    # Minimum cosine SIMILARITY a chunk must reach to count as a retrieval hit.
    # Convention: pgvector's ``<=>`` operator returns cosine DISTANCE (0 = identical,
    # 2 = opposite); similarity = 1 - distance.  A hit therefore requires:
    #   distance ≤ 1 - rag_similarity_min
    # i.e. with the default 0.25 a chunk must score at least 0.25 similarity
    # (≤ 0.75 distance) to be included.  Chunks below this threshold are dropped;
    # when every chunk is dropped the retrieval is treated as empty and the agent
    # reports "no information" (anti-hallucination path).
    # req: faq-rag-009, faq-rag-011
    rag_similarity_min: float = 0.25

    # Embedding model — OpenAI text-embedding-3-small routed through the SAME Pydantic AI
    # Gateway as the chat models (one token: PYDANTIC_AI_GATEWAY_API_KEY). Chosen over
    # Gemini embeddings, which would need a separate GOOGLE_API_KEY (the gateway token does
    # not cover Gemini embeddings). Consumed via pydantic_ai.Embedder.
    # req: faq-rag-005
    embedding_model: str = "gateway/openai:text-embedding-3-small"

    # Dimensionality of the pgvector embedding column — fixed by the chosen model
    # (text-embedding-3-small @ 1536 dims).  Changing this requires a column-level migration
    # and a full re-embed of all DocumentChunk rows.
    # req: faq-rag-005
    embedding_dim: int = 1536

    # Size of each text chunk (in characters) produced by the ingestion splitter.
    # req: faq-rag-005
    chunk_size: int = 1000

    # Overlap between consecutive chunks (in characters) to preserve sentence context
    # across chunk boundaries.
    # req: faq-rag-005
    chunk_overlap: int = 150


@lru_cache
def get_settings() -> Settings:
    """Return the cached, process-wide :class:`Settings` instance.

    Lazy + cached so importing this module never instantiates ``Settings`` (which would
    fail when required env vars are absent, e.g. in static analysis / CI import checks).
    """
    return Settings()
