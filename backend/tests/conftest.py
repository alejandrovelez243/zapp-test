"""Shared fixtures for the backend test suite.

The lru_cache on get_settings and get_orchestrator persists across tests in the same
process.  Every test gets a fresh settings + orchestrator load so monkeypatch.setenv
takes effect correctly and stale model state does not bleed between test functions.
"""

from collections.abc import Generator

import pytest

from app.agents.orchestrator import get_orchestrator
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
