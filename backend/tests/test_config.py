"""Tests for app/config.py (Settings) and app/observability.py no-op behaviour.

Requirements:
- platform-scaffold-012: single config module with model ids +
  supported=("es","en","pt") / fallback_lang="en"; only DATABASE_URL + ADMIN_TOKEN
  are required — no LLM provider key is required.
- platform-scaffold-013: IF LOGFIRE_TOKEN or POSTHOG_KEY is absent THEN the system
  shall start without error (configure_observability is a safe no-op).
"""

import pytest
from fastapi import FastAPI

import app.observability as _obs_module
from app.config import get_settings
from app.observability import configure_observability


def test_settings_load_with_required_fields_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings load succeeds with only DATABASE_URL + ADMIN_TOKEN set.

    No LLM provider key is required — PydanticAI reads provider keys directly from env.
    # platform-scaffold-012
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
    monkeypatch.setenv("ADMIN_TOKEN", "super-secret-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("POSTHOG_KEY", raising=False)

    settings = get_settings()

    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost/testdb"
    assert settings.admin_token == "super-secret-token"


def test_supported_languages_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """supported == ('es', 'en', 'pt') and fallback_lang == 'en'.  # platform-scaffold-012"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
    monkeypatch.setenv("ADMIN_TOKEN", "tok")

    settings = get_settings()

    assert settings.supported == ("es", "en", "pt")
    assert settings.fallback_lang == "en"


def test_optional_llm_keys_default_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider API keys are None when absent — no LLM key is required.  # platform-scaffold-012"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ADMIN_TOKEN", "tok")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    settings = get_settings()

    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None
    assert settings.gemini_api_key is None


def test_configure_observability_noop_without_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """configure_observability does not raise when LOGFIRE_TOKEN and POSTHOG_KEY are absent.

    The _initialized guard is temporarily cleared so the full code path (token checks,
    settings load) is exercised rather than the early-return shortcut.
    # platform-scaffold-013
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ADMIN_TOKEN", "tok")
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("POSTHOG_KEY", raising=False)

    # Temporarily clear the idempotency guard so the full no-token path is exercised.
    saved_initialized = _obs_module._initialized
    _obs_module._initialized = False
    try:
        configure_observability(FastAPI())  # must not raise
    finally:
        _obs_module._initialized = saved_initialized
