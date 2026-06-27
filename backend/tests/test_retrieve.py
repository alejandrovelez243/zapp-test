"""Unit tests for app/rag/retrieve.py — cosine retrieval.

All DB I/O and embedding calls are mocked — no real Postgres / pgvector /
gateway calls are made.  The real pgvector ordering and distance arithmetic
are exercised via Docker Postgres + the eval suite (Task 12).

Mocking strategy
----------------
- ``db`` (AsyncSession):  ``AsyncMock(spec=AsyncSession)`` whose ``.execute``
  method returns a ``MagicMock`` with ``.all()`` pre-loaded with namedtuple
  rows (text, document_id, distance).  Using a ``namedtuple`` mirrors the
  attribute-access pattern that ``retrieve`` uses on real SQLAlchemy ``Row``
  objects (``row.text``, ``row.document_id``, ``row.distance``).
- ``embedder``:  plain ``AsyncMock`` with ``embed_query`` returning a list of
  floats; the content doesn't matter for unit tests because we mock the DB
  execution side and never exercise actual pgvector arithmetic here.

Test classes
------------
- ``TestTopKOrdering``       — lower distance → higher similarity → earlier in list.
- ``TestDistanceToSimilarity`` — score = 1.0 - distance conversion.
- ``TestThresholdDrop``      — hits below ``similarity_min`` excluded; all-below → [].
- ``TestStatusFilter``       — ``Document.status == "ready"`` present in the SQL.

Requirements: faq-rag-009 (cosine retrieve), faq-rag-004 (status filter)
Design contract: specs/faq-rag/design.md §2.4
"""

from __future__ import annotations

from collections import namedtuple
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.retrieve import retrieve

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Mimics the attribute-access shape of a real SQLAlchemy Row
# (row.text, row.document_id, row.distance).
_Row = namedtuple("_Row", ["text", "document_id", "distance"])

_DEFAULT_VEC: list[float] = [0.1] * 10  # short stub; real dim doesn't matter here


def _make_db(rows: list[Any]) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns ``rows`` from .all()."""
    mock_result: MagicMock = MagicMock()
    mock_result.all.return_value = rows
    mock_db: AsyncMock = AsyncMock(spec=AsyncSession)
    mock_db.execute.return_value = mock_result
    return mock_db


def _make_embedder(vec: list[float] | None = None) -> AsyncMock:
    """Return a fake embedder whose embed_query returns ``vec``."""
    embedder: AsyncMock = AsyncMock()
    embedder.embed_query = AsyncMock(return_value=vec or _DEFAULT_VEC)
    return embedder


# ---------------------------------------------------------------------------
# TestTopKOrdering
# ---------------------------------------------------------------------------


class TestTopKOrdering:
    """Lower distance (higher similarity) comes first in returned list.

    The SQL already orders by distance ASC (``ORDER BY distance``); retrieve()
    preserves that order and just converts units.  Tests here verify end-to-end
    ordering of the Hit list returned to the caller.

    req: faq-rag-009
    """

    async def test_two_hits_ordered_by_similarity_desc(self) -> None:
        """First hit has lower distance (higher similarity) than second.

        req: faq-rag-009 — top-k ordering by cosine similarity descending.
        """
        rows = [
            _Row(text="near chunk", document_id=1, distance=0.1),
            _Row(text="far chunk", document_id=2, distance=0.4),
        ]
        hits = await retrieve(_make_db(rows), "query", _make_embedder(), k=5, similarity_min=0.0)

        assert len(hits) == 2
        assert hits[0].text == "near chunk"
        assert hits[0].score == pytest.approx(0.9)  # 1 - 0.1
        assert hits[1].text == "far chunk"
        assert hits[1].score == pytest.approx(0.6)  # 1 - 0.4

    async def test_single_hit_returned(self) -> None:
        """A single qualifying row returns a list of exactly one Hit."""
        rows = [_Row(text="only chunk", document_id=7, distance=0.3)]
        hits = await retrieve(_make_db(rows), "ethics?", _make_embedder(), k=1, similarity_min=0.0)

        assert len(hits) == 1
        assert hits[0].text == "only chunk"
        assert hits[0].document_id == 7

    async def test_hit_fields_preserved(self) -> None:
        """text, score, and document_id are populated correctly on each Hit."""
        rows = [_Row(text="Plato's Republic", document_id=42, distance=0.15)]
        hits = await retrieve(_make_db(rows), "republic", _make_embedder(), k=1, similarity_min=0.0)

        hit = hits[0]
        assert hit.text == "Plato's Republic"
        assert hit.score == pytest.approx(0.85)  # 1 - 0.15
        assert hit.document_id == 42


# ---------------------------------------------------------------------------
# TestDistanceToSimilarity
# ---------------------------------------------------------------------------


class TestDistanceToSimilarity:
    """score = 1.0 - distance; Hit.score is cosine similarity.

    pgvector ``<=>`` returns cosine DISTANCE in [0, 2] for unit vectors.
    For normalised embeddings the practical range is [0, 1].  The conversion
    must be exact: ``similarity = 1 - distance``.

    req: faq-rag-009
    """

    async def test_distance_zero_gives_similarity_one(self) -> None:
        """Identical vector → distance 0 → similarity 1.0."""
        rows = [_Row(text="identical", document_id=10, distance=0.0)]
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=1, similarity_min=0.0)

        assert hits[0].score == pytest.approx(1.0)

    async def test_distance_one_gives_similarity_zero(self) -> None:
        """Orthogonal vectors → distance 1 → similarity 0.0."""
        rows = [_Row(text="orthogonal", document_id=11, distance=1.0)]
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=1, similarity_min=0.0)

        assert hits[0].score == pytest.approx(0.0)

    async def test_half_distance_gives_half_similarity(self) -> None:
        """distance = 0.5 → similarity = 0.5."""
        rows = [_Row(text="half", document_id=12, distance=0.5)]
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=1, similarity_min=0.0)

        assert hits[0].score == pytest.approx(0.5)

    async def test_score_is_float_not_int(self) -> None:
        """Hit.score is a float even when distance is an integer-valued float."""
        rows = [_Row(text="t", document_id=1, distance=1)]
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=1, similarity_min=0.0)

        assert isinstance(hits[0].score, float)


# ---------------------------------------------------------------------------
# TestThresholdDrop
# ---------------------------------------------------------------------------


class TestThresholdDrop:
    """Hits below ``similarity_min`` are excluded; all-below → empty list [].

    The empty-list case is the anti-hallucination path: the caller receives no
    chunks and must not invent an answer.

    req: faq-rag-009, faq-rag-011 (anti-hallucination path)
    """

    async def test_hit_below_threshold_dropped(self) -> None:
        """Row with similarity < similarity_min is excluded from results."""
        rows = [
            _Row(text="good", document_id=1, distance=0.2),  # sim=0.8 → kept
            _Row(text="weak", document_id=2, distance=0.85),  # sim=0.15 → dropped
        ]
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=5, similarity_min=0.25)

        assert len(hits) == 1
        assert hits[0].text == "good"

    async def test_all_below_threshold_returns_empty(self) -> None:
        """All rows below similarity_min → returns [], the anti-hallucination path.

        req: faq-rag-009, faq-rag-011
        """
        rows = [
            _Row(text="bad1", document_id=1, distance=0.9),  # sim=0.1
            _Row(text="bad2", document_id=2, distance=0.95),  # sim=0.05
        ]
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=5, similarity_min=0.25)

        assert hits == []

    async def test_exactly_at_threshold_is_included(self) -> None:
        """Similarity exactly equal to similarity_min is included (>= check).

        req: faq-rag-009 — boundary condition.
        """
        rows = [_Row(text="at-limit", document_id=5, distance=0.75)]  # sim=0.25
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=1, similarity_min=0.25)

        assert len(hits) == 1
        assert hits[0].text == "at-limit"

    async def test_no_rows_from_db_returns_empty(self) -> None:
        """Empty DB result (DB returns zero rows) → empty list."""
        hits = await retrieve(_make_db([]), "q", _make_embedder(), k=5, similarity_min=0.25)

        assert hits == []

    async def test_mixed_rows_only_qualifying_returned(self) -> None:
        """Multiple rows; only those at or above threshold appear in result."""
        rows = [
            _Row(text="best", document_id=1, distance=0.1),  # sim=0.9 → kept
            _Row(text="ok", document_id=2, distance=0.6),  # sim=0.4 → kept
            _Row(text="poor", document_id=3, distance=0.8),  # sim=0.2 → dropped
        ]
        hits = await retrieve(_make_db(rows), "q", _make_embedder(), k=5, similarity_min=0.25)

        assert len(hits) == 2
        texts = [h.text for h in hits]
        assert "best" in texts
        assert "ok" in texts
        assert "poor" not in texts


# ---------------------------------------------------------------------------
# TestStatusFilter
# ---------------------------------------------------------------------------


class TestStatusFilter:
    """Document.status == 'ready' must be present in the generated SQL statement.

    The test captures the SQLAlchemy Select passed to ``db.execute`` and
    compiles its WHERE clause to verify the status predicate.  Compiling only
    the WHERE clause (not the full statement) avoids serialising the pgvector
    vector parameter which requires a real dialect/connection.

    req: faq-rag-004 — only chunks from 'ready' documents are retrieved.
    """

    async def test_status_ready_in_where_clause(self) -> None:
        """The compiled WHERE clause contains the literal string 'ready'.

        req: faq-rag-004
        """
        captured: list[Any] = []

        async def fake_execute(stmt: Any) -> MagicMock:
            captured.append(stmt)
            mock_result: MagicMock = MagicMock()
            mock_result.all.return_value = []
            return mock_result

        mock_db: AsyncMock = AsyncMock(spec=AsyncSession)
        mock_db.execute.side_effect = fake_execute

        await retrieve(mock_db, "philosophy", _make_embedder(), k=3, similarity_min=0.0)

        assert captured, "db.execute() was not called"
        where_clause = captured[0].whereclause
        assert where_clause is not None, "No WHERE clause on the generated statement"
        # Compile only the WHERE clause with literal_binds so 'ready' is rendered
        # as a SQL literal — safe here because the WHERE clause contains only a
        # plain string parameter (no Vector type to serialise).
        where_str = str(where_clause.compile(compile_kwargs={"literal_binds": True}))
        assert "ready" in where_str, f"'ready' not found in WHERE clause: {where_str!r}"

    async def test_execute_called_once_per_retrieve(self) -> None:
        """retrieve() calls db.execute() exactly once (one SQL round-trip).

        req: faq-rag-009
        """
        db = _make_db([])
        await retrieve(db, "q", _make_embedder(), k=5, similarity_min=0.0)

        db.execute.assert_awaited_once()

    async def test_embed_query_called_with_user_query(self) -> None:
        """retrieve() passes the raw query string to embedder.embed_query.

        req: faq-rag-009 — embed is the first step, query string is forwarded.
        """
        db = _make_db([])
        embedder = _make_embedder()

        await retrieve(db, "What is Stoicism?", embedder, k=5, similarity_min=0.0)

        embedder.embed_query.assert_awaited_once_with("What is Stoicism?")
