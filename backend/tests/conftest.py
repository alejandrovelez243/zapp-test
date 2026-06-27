"""Shared fixtures for the backend test suite.

The lru_cache on get_settings and get_orchestrator persists across tests in the same
process.  Every test gets a fresh settings + orchestrator load so monkeypatch.setenv
takes effect correctly and stale model state does not bleed between test functions.
"""

from collections.abc import Generator

import pytest

from app.agents.orchestrator import get_orchestrator
from app.config import get_settings
from app.guardrails.llm import get_guardrail_classifier


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
def _clear_guardrail_classifier_cache() -> Generator[None, None, None]:
    """Clear the lru_cache on get_guardrail_classifier before and after every test.

    Pre-test clear: ensures the classifier agent is re-constructed with the test's
    env vars (including any monkeypatched values such as GUARDRAILS_LLM_ENABLED).
    Post-test clear: prevents a stale agent instance from leaking into the next test.
    """
    get_guardrail_classifier.cache_clear()
    yield
    get_guardrail_classifier.cache_clear()


@pytest.fixture(autouse=True)
def _set_gateway_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a dummy PYDANTIC_AI_GATEWAY_API_KEY so get_orchestrator() can construct.

    The default model strings are now ``gateway/anthropic:...``.  pydantic-ai 2.0
    resolves the provider eagerly in ``Agent.__init__`` and reads
    ``PYDANTIC_AI_GATEWAY_API_KEY`` from env via ``gateway_provider()``.  A dummy key
    in the ``pylf_v1_<region>_<suffix>`` format satisfies the pattern check in
    ``_infer_base_url`` so no ``UserError`` is raised at construction time.

    The ``.override(TestModel(...)`` / ``.override(FunctionModel(...))`` calls in each
    test still handle actual runs — no real gateway request is ever made.
    """
    monkeypatch.setenv("PYDANTIC_AI_GATEWAY_API_KEY", "pylf_v1_us_testdummykey")
