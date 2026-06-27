"""EmbeddingService — wraps pydantic_ai.Embedder for FAQ-RAG.

Provides:
  - EmbeddingError   — typed exception raised on any embed failure; callers must
                       handle it explicitly (never swallowed silently):
                         ingest path  → mark Document.status = "failed"
                         query path   → degrade to needs_review=True + low confidence_score
  - EmbeddingService — stateless service with lazy Embedder construction;
                       delegates embed_documents / embed_query to the
                       pydantic_ai.Embedder (gateway/openai:text-embedding-3-small,
                       dim 1536), each call wrapped in a logfire.span("embed") trace.
  - get_embedding_service() — @lru_cache singleton factory (mirrors get_orchestrator /
                       get_judge); importing this module requires NO gateway key.

Lazy construction: the pydantic_ai.Embedder is built on first use (Embedder.__init__
uses defer_model_check=True by default, so no provider key is touched at construction
time — only at the first network call).

Real Embedder API confirmed at runtime (probe: pydantic_ai 2.0):
  embed_documents(documents: str | Sequence[str]) -> Coroutine[EmbeddingResult]
  embed_query(query: str | Sequence[str])         -> Coroutine[EmbeddingResult]
  EmbeddingResult.embeddings: Sequence[Sequence[float]]

Requirements: faq-rag-005, faq-rag-017
Design contract: specs/faq-rag/design.md §2.2
"""

from __future__ import annotations

from functools import lru_cache

import logfire
from pydantic_ai import Embedder

from app.config import get_settings


class EmbeddingError(Exception):
    """Raised when an embed call fails (gateway error, timeout, etc.).

    Callers MUST handle this explicitly — it is NEVER swallowed silently here.
      - Ingest job  → catch, set Document.status = "failed", store exc message.
      - Query path  → catch, degrade to needs_review=True with low confidence_score.

    req: faq-rag-017
    """


class EmbeddingService:
    """Stateless service that embeds text via pydantic_ai.Embedder.

    Construction is LAZY: the underlying pydantic_ai.Embedder is built only on
    the first embed call, so:
      - import app.rag.embeddings   → no env required
      - EmbeddingService()          → no env required
      - svc.embed_documents([...])  → requires PYDANTIC_AI_GATEWAY_API_KEY

    All calls are wrapped in a logfire.span("embed") so they appear as child
    spans inside the ingest-job or retrieve Logfire trace tree. Span attributes
    record the kind ("documents" | "query") and, for batches, the input count.

    req: faq-rag-005, faq-rag-017
    Design contract: specs/faq-rag/design.md §2.2
    """

    def __init__(self) -> None:
        # Typed None; built lazily on first use (see _get_embedder).
        self._embedder: Embedder | None = None

    def _get_embedder(self) -> Embedder:
        """Return the cached Embedder, constructing it on first call.

        Reads embedding_model from settings (the single config source).
        pydantic_ai.Embedder(model) with the default defer_model_check=True
        does not touch the provider key here — only at the first network call.
        """
        embedder = self._embedder
        if embedder is None:
            model: str = get_settings().embedding_model
            embedder = Embedder(model)
            self._embedder = embedder
        return embedder

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document chunks.

        Delegates to pydantic_ai.Embedder.embed_documents (one batched API
        call), wraps in a logfire.span("embed") so the Logfire trace shows the
        batch size and model used. On any failure raises EmbeddingError — never
        swallows.

        Args:
            texts: List of chunk strings to embed (may be a single-element list).

        Returns:
            One embedding vector (list[float]) per input text, in the same
            order. Vector length equals settings.embedding_dim (1536).

        Raises:
            EmbeddingError: On gateway errors, timeouts, or unexpected failures.

        req: faq-rag-005, faq-rag-017
        """
        embedder = self._get_embedder()
        with logfire.span("embed", embed_kind="documents", input_count=len(texts)):
            try:
                result = await embedder.embed_documents(texts)
                # EmbeddingResult.embeddings: Sequence[Sequence[float]]
                # Convert to list[list[float]] for callers (JSON-serialisable, typed).
                return [list(vec) for vec in result.embeddings]
            except Exception as exc:
                raise EmbeddingError(f"embed_documents failed: {exc}") from exc

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for retrieval.

        Delegates to pydantic_ai.Embedder.embed_query, wraps in a
        logfire.span("embed"). On any failure raises EmbeddingError — never
        swallows.

        Args:
            text: The query string to embed.

        Returns:
            A single embedding vector (list[float], length = embedding_dim).

        Raises:
            EmbeddingError: On gateway errors, timeouts, or unexpected failures.

        req: faq-rag-005, faq-rag-017
        """
        embedder = self._get_embedder()
        with logfire.span("embed", embed_kind="query"):
            try:
                result = await embedder.embed_query(text)
                # result.embeddings[0] is the single query vector.
                return list(result.embeddings[0])
            except Exception as exc:
                raise EmbeddingError(f"embed_query failed: {exc}") from exc


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Return the process-wide EmbeddingService singleton (lazy factory).

    Mirrors get_orchestrator / get_judge: importing this module never touches
    any provider key or environment variable. EmbeddingService itself defers
    the Embedder construction to the first embed call.

    req: faq-rag-005
    """
    return EmbeddingService()
