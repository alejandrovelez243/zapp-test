"""Shared fixtures for the backend test suite.

The lru_cache on get_settings, get_orchestrator, and get_guarded_orchestrator persists
across tests in the same process.  Every test gets a fresh settings + agent load so
monkeypatch.setenv takes effect correctly and stale model state does not bleed between
test functions.
"""

from collections.abc import Generator

import pytest

from app.agents.orchestrator import get_guarded_orchestrator, get_orchestrator
from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None, None, None]:
    """Clear the lru_cache on get_settings before and after every test.

    Pre-test clear: ensures monkeypatch.setenv is visible to Settings.__init__.
    Post-test clear: prevents a test's env-var state from bleeding into the next test.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_orchestrator_cache() -> Generator[None, None, None]:
    """Clear the lru_cache on get_orchestrator before and after every test.

    Pre-test clear: ensures the orchestrator is re-constructed with the test's
    env vars (including the API key set via monkeypatch).
    Post-test clear: prevents a stale agent instance from leaking into the next test.
    """
    get_orchestrator.cache_clear()
    yield
    get_orchestrator.cache_clear()


@pytest.fixture(autouse=True)
def _clear_guarded_orchestrator_cache() -> Generator[None, None, None]:
    """Clear the lru_cache on get_guarded_orchestrator before and after every test.

    Pre-test clear: ensures the GuardedAgent is re-constructed with the test's
    env vars and the freshly-cleared underlying orchestrator.
    Post-test clear: prevents a stale GuardedAgent from leaking into the next test.
    """
    get_guarded_orchestrator.cache_clear()
    yield
    get_guarded_orchestrator.cache_clear()


@pytest.fixture(autouse=True)
def _set_gateway_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars so Settings + get_orchestrator() can construct.

    Sets:
      - ``PYDANTIC_AI_GATEWAY_API_KEY`` — the gateway key required by pydantic-ai 2.0
        ``Agent.__init__``; the ``pylf_v1_<region>_<suffix>`` format satisfies the
        pattern check in ``_infer_base_url`` without a real key.
      - ``DATABASE_URL`` — required by Settings; tests that need a real DB override
        this with aiosqlite in their own fixtures.
      - ``ADMIN_TOKEN`` — required by Settings.

    The ``.override(TestModel(...)`` / ``.override(FunctionModel(...))`` calls in each
    test still handle actual runs — no real gateway request is ever made.
    """
    monkeypatch.setenv("PYDANTIC_AI_GATEWAY_API_KEY", "pylf_v1_us_testdummykey")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-conftest")
