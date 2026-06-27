"""Cosine similarity retrieval over DocumentChunk via pgvector.

``retrieve`` is the primary search surface for the FAQ-RAG pipeline:
  1. Embed the user query via ``EmbeddingService.embed_query`` (one gateway call,
     wrapped in a Logfire span inside the service).
  2. Run a pgvector cosine-distance SQL query against ``DocumentChunk`` rows
     that belong to a ``Document`` with ``status == "ready"``.
  3. Convert pgvector distance (0 = identical, 2 = opposite) to cosine similarity
     (similarity = 1 - distance), keeping the result in [0, 1] for well-formed
     normalised vectors.
  4. Drop hits below ``similarity_min`` and return the surviving ``Hit`` objects
     ordered by similarity descending (highest first).

An **empty result list** (no chunk reaches ``similarity_min``) is the intentional
anti-hallucination path: the caller (``faq_agent.retrieve_chunks`` tool) receives an
empty list and falls back to "I don't have that information" without inventing facts.

Hybrid retrieval (keyword score fused with cosine) is defined in Task 10 and is NOT
implemented here.  A clearly labelled seam is left in the function body so Task 10
can add the branch without restructuring the function.

Requirements:
  faq-rag-009 — cosine top-k retrieval
  faq-rag-004 — only ``status=ready`` documents are retrieved

Design contract: specs/faq-rag/design.md §2.4
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.embeddings import EmbeddingService
from app.rag.models import Document, DocumentChunk


class Hit(BaseModel):
    """A single retrieval result: chunk text, cosine similarity, and source document.

    ``score`` is cosine SIMILARITY (1 - pgvector cosine distance), in [0, 1]
    where 1 = identical and 0 = orthogonal.  The caller (``retrieve_chunks`` tool)
    records ``max(hit.score for hit in hits)`` onto ``ctx.deps.rag.max_score``.

    req: faq-rag-009
    """

    # Raw chunk text returned to the faq_agent as grounding context.
    text: str

    # Cosine similarity: 1.0 = identical, 0.0 = orthogonal (higher is better).
    score: float

    # Foreign key to the parent Document row (used by the validator for logging).
    document_id: int


async def retrieve(
    db: AsyncSession,
    query: str,
    embedder: EmbeddingService,
    *,
    k: int,
    similarity_min: float,
) -> list[Hit]:
    """Return the top-k cosine-similar DocumentChunk hits for ``query``.

    Only chunks whose parent ``Document`` has ``status == "ready"`` are queried.
    Hits whose cosine similarity (``1 - pgvector distance``) falls below
    ``similarity_min`` are dropped from the returned list.

    pgvector distance convention
    ----------------------------
    The ``<=>`` operator returns cosine DISTANCE, where:
      0   = identical vectors
      1   = orthogonal vectors
      2   = opposite vectors (fully anti-correlated)
    Cosine SIMILARITY = 1 - distance.  A hit requires:
      distance ≤ 1 - similarity_min   (equivalently: similarity ≥ similarity_min)

    Args:
        db:             Async SQLAlchemy session (injected from ``AgentDeps``).
        query:          The user's question / search string.
        embedder:       ``EmbeddingService`` instance; supplies ``embed_query``.
        k:              Maximum rows to fetch from pgvector before threshold
                        filtering.  Maps to the SQL ``LIMIT``.
        similarity_min: Minimum cosine similarity (inclusive) to accept a chunk.
                        Chunks below this threshold are silently dropped.
                        Use ``settings.rag_similarity_min`` from the call site.

    Returns:
        List of :class:`Hit` ordered by similarity descending (highest first).
        An empty list when no chunk reaches ``similarity_min`` — this is the
        intentional anti-hallucination path (req: faq-rag-011).

    Raises:
        EmbeddingError: Propagated when ``embedder.embed_query`` fails.  The
                        caller is responsible for degrading
                        (``needs_review=True``, lower ``confidence_score``).

    req: faq-rag-009, faq-rag-004
    Design contract: specs/faq-rag/design.md §2.4
    """
    # ------------------------------------------------------------------
    # Step 1: Embed the query.
    # EmbeddingError propagates — the caller must catch and degrade.
    # req: faq-rag-009
    # ------------------------------------------------------------------
    qvec: list[float] = await embedder.embed_query(query)

    # ------------------------------------------------------------------
    # Step 2: pgvector cosine-distance SQL query.
    # ``<=>`` (cosine distance) is exposed as ``.cosine_distance()`` on the
    # Vector-typed column.  mypy cannot see this method through the
    # ``list[float]`` annotation, so the attr-defined ignore is required.
    # The JOIN + WHERE on ``Document.status == "ready"`` is the status gate.
    # req: faq-rag-009 (cosine top-k), faq-rag-004 (status filter)
    # ------------------------------------------------------------------
    distance_col = DocumentChunk.embedding.cosine_distance(qvec)  # type: ignore[attr-defined]
    stmt = (
        select(  # type: ignore[call-overload]
            DocumentChunk.text,
            DocumentChunk.document_id,
            distance_col.label("distance"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.status == "ready")
        .order_by(distance_col)
        .limit(k)
    )

    result = await db.execute(stmt)
    rows = result.all()

    # ------------------------------------------------------------------
    # Step 3: Convert distance → similarity; drop hits below threshold.
    # pgvector ``<=>`` returns cosine DISTANCE ∈ [0, 2] for normalised
    # vectors; real hits fall in [0, 1], so 1 - distance ∈ [0, 1].
    # req: faq-rag-009
    # ------------------------------------------------------------------
    hits: list[Hit] = []
    for row in rows:
        similarity: float = 1.0 - float(row.distance)
        if similarity >= similarity_min:
            hits.append(
                Hit(
                    text=str(row.text),
                    score=similarity,
                    document_id=int(row.document_id),
                )
            )

    # ------------------------------------------------------------------
    # SEAM: Task 10 (hybrid_retrieval) adds keyword scoring here.
    # When hybrid=True, keyword scores (Postgres ILIKE / ts_rank) are
    # fused with ``similarity`` and rows are re-ranked before threshold
    # filtering.  That logic is intentionally absent — add it in Task 10
    # without changing the rest of this function.
    # ------------------------------------------------------------------

    return hits
