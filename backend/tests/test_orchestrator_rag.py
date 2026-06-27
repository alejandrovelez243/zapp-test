"""TestModel smoke tests for the ask_faq tool + _reconcile_rag output validator.

Verifies:
  1. Empty retrieval (deps.rag.populated=True, hit_count=0) → _reconcile_rag sets
     needs_review=True and caps confidence_score to ≤ 0.3.
  2. Good retrieval (populated=True, hit_count=3, max_score=0.9) → _reconcile_rag
     does NOT damp confidence_score (stays above 0.3) and does NOT set needs_review.
  3. FAQ tool never called (populated=False, defaults) → _reconcile_rag is a no-op.

All tests use TestModel(call_tools=[]) to skip tool execution so the pre-set
deps.rag state is preserved through the run.  A valid-format dummy gateway key is
supplied by the conftest._set_gateway_key autouse fixture.

Requirements: faq-rag-011, faq-rag-014, faq-rag-015
Design contract: specs/faq-rag/design.md §2.6
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.faq import get_faq_agent
from app.agents.orchestrator import get_orchestrator
from app.deps import AgentDeps, RagSignal
from app.lang.detector import DetectionResult
from app.lang.state import ActiveLangDecision

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEST_ENV_VARS: dict[str, str] = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "ADMIN_TOKEN": "test-admin-token",
}


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set DATABASE_URL and ADMIN_TOKEN so get_settings() succeeds."""
    for key, val in _TEST_ENV_VARS.items():
        monkeypatch.setenv(key, val)


@pytest.fixture(autouse=True)
def _clear_faq_cache() -> Generator[None, None, None]:
    """Clear get_faq_agent lru_cache before and after each test."""
    get_faq_agent.cache_clear()
    yield
    get_faq_agent.cache_clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Valid TurnOutput args: high initial confidence, no review flag.
# The output validators will overwrite confidence_score and needs_review.
_HIGH_CONFIDENCE_ARGS: dict[str, object] = {
    "reply": "I don't have that information.",
    "detected_lang": "en",
    "active_lang": "en",
    "lang_confidence": 0.95,
    "final_normalized_text": "What courses are offered?",
    "detected_country": None,
    "confidence_score": 0.9,
    "needs_review": False,
    "guardrails": {"input": [], "output": []},
}


def _make_good_deps() -> AgentDeps:
    """Return AgentDeps with a reliable English detection — avoids language-validator noise.

    Using a reliable detection (lang="en", confidence=0.95, is_reliable=True) ensures
    _reconcile_language does not raise ModelRetry or set needs_review independently,
    keeping the test focused on _reconcile_rag's behaviour.
    """
    return AgentDeps(
        session=AsyncMock(spec=AsyncSession),
        http=AsyncMock(spec=httpx.AsyncClient),
        session_id="rag-smoke",
        request_ip="127.0.0.1",
        active_lang="en",
        detection=DetectionResult(lang="en", confidence=0.95, is_reliable=True),
        lang_decision=ActiveLangDecision(
            active_lang="en",
            first_turn=True,
            locked=False,
            fallback_used=False,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReconcileRagValidator:
    """Smoke tests for the _reconcile_rag output_validator.

    Uses TestModel(call_tools=[]) to skip actual tool execution so the pre-set
    deps.rag signal is preserved and the validator sees it unmodified.

    req: faq-rag-011, faq-rag-015
    """

    async def test_empty_retrieval_lowers_confidence_and_sets_needs_review(self) -> None:
        """Empty retrieval: hit_count=0, populated=True → needs_review=True + confidence_score≤0.3.

        Simulates: ask_faq was called (populated=True) but the FAQ agent found no
        matching chunks (hit_count=0, max_score=None).  The _reconcile_rag validator
        must cap confidence_score at 0.3 and set needs_review=True to prevent a
        high-confidence hallucination from being delivered to the student.

        req: faq-rag-011 (empty-retrieval → needs_review via validator)
             faq-rag-015 (RagSignal → confidence dampening)
        """
        deps = _make_good_deps()
        # Simulate: ask_faq was called but retrieval was empty.
        deps.rag.populated = True
        deps.rag.hit_count = 0
        deps.rag.max_score = None

        # call_tools=[] skips tool execution so pre-set rag state is preserved.
        with get_orchestrator().override(
            model=TestModel(call_tools=[], custom_output_args=_HIGH_CONFIDENCE_ARGS)
        ):
            result = await get_orchestrator().run(
                "What courses are offered?",
                deps=deps,
            )

        turn = result.output
        # req: faq-rag-011 — empty retrieval → validator sets needs_review=True
        assert turn.needs_review is True, (
            f"Expected needs_review=True for empty retrieval, got {turn.needs_review}"
        )
        # req: faq-rag-015 — validator caps confidence_score at 0.3
        assert turn.confidence_score <= 0.3, (
            f"Expected confidence_score≤0.3 for empty retrieval, got {turn.confidence_score}"
        )

    async def test_good_retrieval_no_rag_driven_downgrade(self) -> None:
        """Good retrieval: hit_count=3, max_score=0.9 → no RAG-driven downgrade.

        Simulates: ask_faq was called and returned 3 high-quality hits (max_score=0.9,
        well above rag_similarity_min=0.25).  The _reconcile_rag validator must NOT
        lower confidence_score and must NOT set needs_review=True.

        req: faq-rag-011, faq-rag-015
        """
        deps = _make_good_deps()
        # Simulate: ask_faq was called and retrieval returned good hits.
        deps.rag.populated = True
        deps.rag.hit_count = 3
        deps.rag.max_score = 0.9  # well above rag_similarity_min (default 0.25)

        with get_orchestrator().override(
            model=TestModel(call_tools=[], custom_output_args=_HIGH_CONFIDENCE_ARGS)
        ):
            result = await get_orchestrator().run(
                "Tell me about Stoicism.",
                deps=deps,
            )

        turn = result.output
        # RAG validator must not have dampened confidence below 0.3.
        # Good geo/lang signals produce confidence_score ≈ 0.8+; _reconcile_rag
        # must leave it untouched for a qualifying retrieval.
        assert turn.confidence_score > 0.3, (
            f"Expected confidence_score>0.3 for good retrieval, got {turn.confidence_score}"
        )
        # RAG validator must not have set needs_review for a good hit.
        # req: faq-rag-015 — no dampening when retrieval is strong
        assert turn.needs_review is False, (
            f"Expected needs_review=False for good retrieval, got {turn.needs_review}"
        )

    async def test_faq_not_called_is_noop(self) -> None:
        """FAQ tool not called (populated=False) → _reconcile_rag is a no-op.

        Simulates a greeting turn where the orchestrator answered from general
        knowledge without invoking ask_faq.  The _reconcile_rag validator must
        leave confidence_score and needs_review untouched.

        req: faq-rag-015 (skip when ask_faq was not called)
        """
        deps = _make_good_deps()
        # Default RagSignal: populated=False, hit_count=0, max_score=None.
        assert deps.rag.populated is False  # guard: default state
        assert deps.rag.hit_count == 0

        with get_orchestrator().override(
            model=TestModel(call_tools=[], custom_output_args=_HIGH_CONFIDENCE_ARGS)
        ):
            result = await get_orchestrator().run(
                "Hello!",
                deps=deps,
            )

        turn = result.output
        # _reconcile_rag must not have dampened confidence for a non-FAQ turn.
        assert turn.confidence_score > 0.3, (
            f"Expected confidence_score>0.3 (no RAG dampening), got {turn.confidence_score}"
        )
        # needs_review must not have been set by _reconcile_rag for a non-FAQ turn.
        assert turn.needs_review is False, (
            f"Expected needs_review=False (no RAG dampening), got {turn.needs_review}"
        )


class TestRagSignalPopulatedField:
    """Unit tests for the populated field added to RagSignal.

    req: faq-rag-011 — populated distinguishes empty-hit from not-called
    """

    def test_populated_defaults_false(self) -> None:
        """RagSignal default: populated=False (FAQ tool not yet called).

        req: faq-rag-011 — default state = not populated
        """
        sig = RagSignal()
        assert sig.populated is False

    def test_populated_can_be_set(self) -> None:
        """RagSignal.populated can be set to True in-place.

        req: faq-rag-011 — ask_faq tool sets it after successful run
        """
        sig = RagSignal()
        sig.populated = True
        assert sig.populated is True

    def test_existing_fields_unaffected(self) -> None:
        """Adding populated field does not change hit_count or max_score defaults.

        req: faq-rag-011 — backward compatibility for existing callers
        """
        sig = RagSignal()
        assert sig.hit_count == 0
        assert sig.max_score is None
        assert sig.populated is False
