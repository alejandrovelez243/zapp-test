"""Shared fixtures for the backend test suite.

The lru_cache on get_settings persists across tests in the same process.  Every test
gets a fresh settings load so monkeypatch.setenv takes effect correctly.
"""

from collections.abc import Generator

import pytest

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
