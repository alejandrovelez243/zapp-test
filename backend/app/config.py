"""Single config source for the backend (pydantic-settings).

This is the ONE place model ids, supported languages, and secrets live; every other
module imports settings from here. Model ids are placeholders confirmed at integration.

Requirements: platform-scaffold-012 (single config module: model ids +
``supported=("es","en","pt")`` / ``fallback_lang="en"``), platform-scaffold-017
(fields correspond to the env vars listed in ``.env.example``).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    database_url: str
    anthropic_api_key: str
    admin_token: str

    # --- Optional tokens (None -> feature initializes in safe no-op mode) ---
    logfire_token: str | None = None
    posthog_key: str | None = None
    ipinfo_token: str | None = None

    # --- Model ids (PLACEHOLDERS; confirmed at integration time) ---
    orchestrator_model: str = "anthropic:claude-opus-4-6"
    worker_model: str = "anthropic:claude-sonnet-4-6"
    judge_model: str = "anthropic:claude-haiku-4-6"

    # --- Language policy (consumed by later features) ---
    supported: tuple[str, ...] = ("es", "en", "pt")
    fallback_lang: str = "en"


@lru_cache
def get_settings() -> Settings:
    """Return the cached, process-wide :class:`Settings` instance.

    Lazy + cached so importing this module never instantiates ``Settings`` (which would
    fail when required env vars are absent, e.g. in static analysis / CI import checks).
    """
    return Settings()
