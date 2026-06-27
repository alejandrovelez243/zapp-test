"""TestModel smoke tests for app/agents/faq.py + RagSignal on AgentDeps.

Verifies:
  1. ``retrieve_chunks`` tool sets ``deps.rag.hit_count`` and ``deps.rag.max_score``
     when hits are returned (canned retrieval via monkeypatch).
  2. Empty retrieval path: ``deps.rag.hit_count == 0`` and ``deps.rag.max_score is None``.
  3. ``RagSignal`` is present in ``AgentDeps.__dataclass_fields__`` and defaults cleanly.

No real Postgres / pgvector / gateway calls are made.  ``retrieve`` is monkeypatched;
the agent runs via ``TestModel`` (default ``call_tools='all'`` in pydantic-ai 2.0,
so the registered ``_retrieve_chunks_impl`` tool IS called during each run).

``EmbeddingService()`` is constructed inside the tool but its first network call
never fires because ``retrieve`` is replaced before the agent runs.

Requirements: faq-rag-010, faq-rag-011, faq-rag-012, faq-rag-013
Design contract: specs/faq-rag/design.md §2.5, §2.8
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.faq import get_faq_agent
from app.deps import AgentDeps, RagSignal
from app.rag.retrieve import Hit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deps() -> AgentDeps:
    """Return minimal ``AgentDeps`` for unit tests (mocked DB + HTTP, no geo)."""
    return AgentDeps(
        session=AsyncMock(spec=AsyncSession),
        http=AsyncMock(spec=httpx.AsyncClient),
        session_id="faq-test-session",
        request_ip="127.0.0.1",
        active_lang="en",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set DATABASE_URL and ADMIN_TOKEN so get_settings() succeeds.

    ``get_faq_agent()`` calls ``get_settings()`` which requires these two fields.
    The conftest ``_set_gateway_key`` fixture already sets
    PYDANTIC_AI_GATEWAY_API_KEY; this fixture supplies the remaining required vars.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")


@pytest.fixture(autouse=True)
def _clear_faq_cache() -> Generator[None, None, None]:
    """Clear the ``get_faq_agent`` lru_cache before and after every test.

    Mirrors the ``_clear_orchestrator_cache`` pattern in conftest: ensures each
    test gets a fresh agent constructed with its monkeypatched env vars, and
    prevents a cached instance from leaking into the next test.
    """
    get_faq_agent.cache_clear()
    yield
    get_faq_agent.cache_clear()


# ---------------------------------------------------------------------------
# TestRagSignalModel — field presence + default construction
# ---------------------------------------------------------------------------


class TestRagSignalModel:
    """``RagSignal`` model shape and ``AgentDeps.rag`` default.

    req: faq-rag-011 (RagSignal on deps — producer side)
         faq-rag-015 (consumer side reads this via orchestrator validator)
    """

    def test_rag_field_present_in_agent_deps_dataclass_fields(self) -> None:
        """``AgentDeps.__dataclass_fields__`` contains 'rag'.

        req: faq-rag-011 — AgentDeps carries the RagSignal holder.
        """
        assert "rag" in AgentDeps.__dataclass_fields__  # type: ignore[attr-defined]

    def test_default_rag_signal_is_zero(self) -> None:
        """``AgentDeps()`` construction yields ``deps.rag.hit_count == 0`` + ``max_score is None``.

        Existing callers that do not pass ``rag`` keep working.
        req: faq-rag-011 (default factory)
        """
        deps = _make_deps()
        assert isinstance(deps.rag, RagSignal)
        assert deps.rag.hit_count == 0
        assert deps.rag.max_score is None

    def test_rag_signal_is_mutable(self) -> None:
        """RagSignal fields can be set in-place (required by retrieve_chunks tool).

        req: faq-rag-011 — tool writes signal without replacing the object.
        """
        sig = RagSignal()
        sig.hit_count = 3
        sig.max_score = 0.85
        assert sig.hit_count == 3
        assert sig.max_score == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# TestRetrieveChunksTool — TestModel smoke via monkeypatched retrieve
# ---------------------------------------------------------------------------


class TestRetrieveChunksTool:
    """Smoke tests for the retrieve_chunks tool via TestModel.

    ``TestModel`` in pydantic-ai 2.0 defaults to ``call_tools='all'``, so the
    registered ``_retrieve_chunks_impl`` tool IS called during each ``agent.run``.
    ``retrieve`` is monkeypatched in the ``app.agents.faq`` namespace so the tool
    returns canned ``Hit`` objects without any real DB or embed call.

    req: faq-rag-010, faq-rag-011, faq-rag-012, faq-rag-013
    """

    async def test_grounded_hits_set_hit_count_and_max_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve_chunks records hit_count=2 and max_score=0.9 for two canned hits.

        TestModel calls the tool with a dummy query string; the monkeypatched
        ``retrieve`` returns two ``Hit`` objects regardless of query content.
        The tool records the RagSignal and returns the chunk texts to the model.

        req: faq-rag-011 (producer side — RagSignal written by retrieve_chunks)
        """
        canned_hits = [
            Hit(text="Stoicism is a school of Hellenistic philosophy.", score=0.9, document_id=1),
            Hit(text="Plato founded the Academy in Athens.", score=0.7, document_id=2),
        ]
        monkeypatch.setattr(
            "app.agents.faq.retrieve",
            AsyncMock(return_value=canned_hits),
        )
        deps = _make_deps()

        with get_faq_agent().override(
            model=TestModel(custom_output_text="Stoicism is a school of philosophy.")
        ):
            await get_faq_agent().run("What is Stoicism?", deps=deps)

        # req: faq-rag-011 — hit_count and max_score reflect the returned hits
        assert deps.rag.hit_count == 2
        assert deps.rag.max_score == pytest.approx(0.9)

    async def test_empty_retrieval_sets_hit_count_zero_and_max_score_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty retrieval path: hit_count == 0 and max_score is None.

        When no chunk meets ``rag_similarity_min`` the tool returns ``[]`` and
        the agent is expected to say it doesn't have the information (anti-hallucination).
        The RagSignal records the empty state so the orchestrator validator can
        damp ``confidence_score`` and set ``needs_review=True``.

        req: faq-rag-011 (empty path), faq-rag-015 (validator reads this)
        """
        monkeypatch.setattr(
            "app.agents.faq.retrieve",
            AsyncMock(return_value=[]),
        )
        deps = _make_deps()

        with get_faq_agent().override(
            model=TestModel(custom_output_text="I don't have that information.")
        ):
            await get_faq_agent().run("Question with no matching document", deps=deps)

        # req: faq-rag-011 — empty retrieval → zero signal
        assert deps.rag.hit_count == 0
        assert deps.rag.max_score is None

    async def test_single_hit_sets_max_score_from_top_hit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single hit: max_score equals that hit's score, hit_count == 1.

        req: faq-rag-011 — max_score is the top-ranked hit's similarity.
        """
        single_hit = [Hit(text="Aristotle's Nicomachean Ethics.", score=0.82, document_id=5)]
        monkeypatch.setattr(
            "app.agents.faq.retrieve",
            AsyncMock(return_value=single_hit),
        )
        deps = _make_deps()

        with get_faq_agent().override(model=TestModel(custom_output_text="Aristotle's Ethics.")):
            await get_faq_agent().run("Tell me about Aristotle.", deps=deps)

        assert deps.rag.hit_count == 1
        assert deps.rag.max_score == pytest.approx(0.82)
