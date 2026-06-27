"""Unit tests for app/rag/embeddings.py — EmbeddingService.

All Embedder I/O is mocked — no real gateway calls are made. The suite is
fully offline and deterministic.

Covers:
  - Import-without-key: module import + EmbeddingService() with no env vars set.
  - embed_documents: delegates to Embedder.embed_documents; returns list[list[float]].
  - embed_query: delegates to Embedder.embed_query; returns list[float] (first vector).
  - EmbeddingError: raised (never swallowed) on any Embedder failure.
  - get_embedding_service: returns the same cached singleton.

Requirements: faq-rag-005, faq-rag-017
Design contract: specs/faq-rag/design.md §2.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.rag.embeddings import EmbeddingError, EmbeddingService, get_embedding_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_result(vectors: list[list[float]]) -> MagicMock:
    """Build a minimal stand-in for pydantic_ai.embeddings.EmbeddingResult.

    Only .embeddings needs to exist for EmbeddingService to consume it.
    """
    mock: MagicMock = MagicMock()
    mock.embeddings = vectors
    return mock


def _service_with_mock_embedder(
    embed_documents_return: MagicMock | None = None,
    embed_query_return: MagicMock | None = None,
    embed_documents_side_effect: Exception | None = None,
    embed_query_side_effect: Exception | None = None,
) -> EmbeddingService:
    """Return an EmbeddingService with a pre-injected mock Embedder.

    Bypasses _get_embedder() so no env vars (DATABASE_URL, ADMIN_TOKEN,
    PYDANTIC_AI_GATEWAY_API_KEY) are required during the test.
    """
    svc = EmbeddingService()
    mock_embedder: MagicMock = MagicMock()

    if embed_documents_side_effect is not None:
        mock_embedder.embed_documents = AsyncMock(side_effect=embed_documents_side_effect)
    else:
        mock_embedder.embed_documents = AsyncMock(return_value=embed_documents_return)

    if embed_query_side_effect is not None:
        mock_embedder.embed_query = AsyncMock(side_effect=embed_query_side_effect)
    else:
        mock_embedder.embed_query = AsyncMock(return_value=embed_query_return)

    # Inject directly: bypasses lazy _get_embedder (no env vars needed).
    svc._embedder = mock_embedder  # type: ignore[assignment]
    return svc


# ---------------------------------------------------------------------------
# Lazy import / construction tests (sync — no network, no env vars)
# ---------------------------------------------------------------------------


def test_import_no_key() -> None:
    """Importing the module + instantiating EmbeddingService requires no key.

    req: faq-rag-005 — lazy construction invariant.
    """
    svc = EmbeddingService()
    assert hasattr(svc, "embed_documents")
    assert hasattr(svc, "embed_query")
    # Embedder is NOT yet built — only on first use.
    assert svc._embedder is None  # type: ignore[has-type]


def test_get_embedding_service_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_embedding_service() returns the same instance on repeated calls.

    req: faq-rag-005 — lru_cache singleton mirrors get_orchestrator pattern.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("ADMIN_TOKEN", "tok")
    get_embedding_service.cache_clear()
    try:
        svc1 = get_embedding_service()
        svc2 = get_embedding_service()
        assert svc1 is svc2
    finally:
        get_embedding_service.cache_clear()


# ---------------------------------------------------------------------------
# embed_documents — happy path
# ---------------------------------------------------------------------------


async def test_embed_documents_returns_list_of_vectors() -> None:
    """embed_documents returns one list[float] per input text, preserving order.

    req: faq-rag-005
    """
    fake_vecs = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    svc = _service_with_mock_embedder(
        embed_documents_return=_fake_result(fake_vecs),
    )

    result = await svc.embed_documents(["text one", "text two"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


async def test_embed_documents_delegates_exact_texts() -> None:
    """embed_documents passes the texts list verbatim to Embedder.embed_documents.

    req: faq-rag-005
    """
    texts = ["chunk A", "chunk B", "chunk C"]
    fake_vecs = [[float(i)] for i in range(len(texts))]
    svc = _service_with_mock_embedder(
        embed_documents_return=_fake_result(fake_vecs),
    )

    await svc.embed_documents(texts)

    svc._embedder.embed_documents.assert_awaited_once_with(texts)  # type: ignore[union-attr]


async def test_embed_documents_single_text() -> None:
    """embed_documents with a single-element list returns a single vector.

    req: faq-rag-005
    """
    svc = _service_with_mock_embedder(
        embed_documents_return=_fake_result([[0.9, 0.8]]),
    )

    result = await svc.embed_documents(["only one"])

    assert result == [[0.9, 0.8]]


# ---------------------------------------------------------------------------
# embed_query — happy path
# ---------------------------------------------------------------------------


async def test_embed_query_returns_single_vector() -> None:
    """embed_query returns the first embedding (the single query vector).

    req: faq-rag-005
    """
    query_vec = [0.11, 0.22, 0.33]
    svc = _service_with_mock_embedder(
        embed_query_return=_fake_result([query_vec]),
    )

    result = await svc.embed_query("What is philosophy?")

    assert result == [0.11, 0.22, 0.33]


async def test_embed_query_delegates_exact_text() -> None:
    """embed_query passes the query string verbatim to Embedder.embed_query.

    req: faq-rag-005
    """
    svc = _service_with_mock_embedder(
        embed_query_return=_fake_result([[0.1]]),
    )

    await svc.embed_query("Aristotle's Ethics")

    svc._embedder.embed_query.assert_awaited_once_with("Aristotle's Ethics")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# EmbeddingError — failure paths (req: faq-rag-017)
# ---------------------------------------------------------------------------


async def test_embed_documents_wraps_runtime_error() -> None:
    """Any exception from Embedder.embed_documents is wrapped in EmbeddingError.

    req: faq-rag-017 — embed failure → callers handle EmbeddingError, never a raw exc.
    """
    svc = _service_with_mock_embedder(
        embed_documents_side_effect=RuntimeError("gateway down"),
    )

    with pytest.raises(EmbeddingError, match="gateway down"):
        await svc.embed_documents(["some text"])


async def test_embed_documents_wraps_timeout_error() -> None:
    """TimeoutError from Embedder is wrapped in EmbeddingError.

    req: faq-rag-017
    """
    svc = _service_with_mock_embedder(
        embed_documents_side_effect=TimeoutError("request timed out"),
    )

    with pytest.raises(EmbeddingError, match="request timed out"):
        await svc.embed_documents(["text"])


async def test_embed_query_wraps_runtime_error() -> None:
    """Any exception from Embedder.embed_query is wrapped in EmbeddingError.

    req: faq-rag-017
    """
    svc = _service_with_mock_embedder(
        embed_query_side_effect=RuntimeError("503 service unavailable"),
    )

    with pytest.raises(EmbeddingError, match="503 service unavailable"):
        await svc.embed_query("question?")


async def test_embed_query_wraps_value_error() -> None:
    """ValueError from Embedder.embed_query is wrapped in EmbeddingError.

    req: faq-rag-017
    """
    svc = _service_with_mock_embedder(
        embed_query_side_effect=ValueError("bad input"),
    )

    with pytest.raises(EmbeddingError, match="bad input"):
        await svc.embed_query("text")


async def test_embedding_error_chains_original_cause() -> None:
    """EmbeddingError preserves the original exception via __cause__.

    req: faq-rag-017 — callers can inspect the root cause for logging.
    """
    original = ConnectionError("network unreachable")
    svc = _service_with_mock_embedder(embed_documents_side_effect=original)

    with pytest.raises(EmbeddingError) as exc_info:
        await svc.embed_documents(["text"])

    assert exc_info.value.__cause__ is original
