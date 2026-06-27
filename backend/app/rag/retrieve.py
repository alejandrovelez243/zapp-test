"""Cosine (or hybrid) similarity retrieval over DocumentChunk via pgvector.

``retrieve`` is the primary search surface for the FAQ-RAG pipeline:
  1. Embed the user query via ``EmbeddingService.embed_query`` (one gateway call,
     wrapped in a Logfire span inside the service).
  2. Build and run a SQL query against ``DocumentChunk`` rows that belong to a
     ``Document`` with ``status == "ready"``.
  3. Convert or use the score, dropping hits below ``similarity_min``, and return
     the surviving ``Hit`` objects ordered by score descending (highest first).

An **empty result list** (no chunk reaches ``similarity_min``) is the intentional
anti-hallucination path: the caller (``faq_agent.retrieve_chunks`` tool) receives an
empty list and falls back to "I don't have that information" without inventing facts.

Two retrieval modes
-------------------
- **Pure cosine** (``hybrid=False``, default): ``ORDER BY embedding <=> :qvec``
  via pgvector HNSW.  ``Hit.score`` is cosine SIMILARITY = 1 - distance, ∈ [0, 1].
- **Hybrid** (``hybrid=True``, Tier-3 feature flag ``settings.hybrid_retrieval``):
  combines the cosine similarity with a Postgres full-text keyword score
  (``ts_rank`` over ``to_tsvector`` / ``plainto_tsquery``) before ranking.  See
  ``_build_hybrid_stmt`` for the exact formula.  ``Hit.score`` is the combined
  score ∈ [0, 1].

The hybrid path adds lexical overlap on top of semantic proximity.  Because
``ts_rank`` values are in [0, 1] and cosine similarity is also in [0, 1], the
weighted sum is semantically compatible with ``similarity_min``.

Helper functions ``_build_cosine_stmt`` and ``_build_hybrid_stmt`` are extracted
to keep ``retrieve`` within the project complexity gate (McCabe ≤ 12).

Requirements:
  faq-rag-009 — cosine top-k retrieval
  faq-rag-004 — only ``status=ready`` documents are retrieved
  faq-rag-016 — hybrid_retrieval flag: fuse keyword score before ranking

Design contract: specs/faq-rag/design.md §2.4
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.embeddings import EmbeddingService
from app.rag.models import Document, DocumentChunk

# ---------------------------------------------------------------------------
# Hybrid retrieval weight constant
# ---------------------------------------------------------------------------
# Weight given to cosine similarity in the hybrid combined score formula:
#
#   combined_score = _HYBRID_ALPHA * cosine_sim + (1 - _HYBRID_ALPHA) * ts_rank_score
#
# Where:
#   _HYBRID_ALPHA = 0.7  (cosine weight — semantic relevance dominates)
#   1 - _HYBRID_ALPHA = 0.3  (keyword weight — lexical overlap as a tiebreaker)
#
# Both cosine_sim and ts_rank_score are in [0, 1], so combined_score ∈ [0, 1].
# The threshold ``similarity_min`` is therefore comparable across both modes.
#
# req: faq-rag-016
_HYBRID_ALPHA: float = 0.7


class Hit(BaseModel):
    """A single retrieval result: chunk text, score, and source document id.

    In **pure cosine** mode, ``score`` is cosine SIMILARITY = 1 - pgvector distance,
    ∈ [0, 1] where 1 = identical vectors and 0 = orthogonal vectors.

    In **hybrid** mode, ``score`` is the combined cosine + keyword score:
    ``_HYBRID_ALPHA * cosine_sim + (1 - _HYBRID_ALPHA) * ts_rank_score``, ∈ [0, 1].

    The caller (``retrieve_chunks`` tool) records
    ``max(hit.score for hit in hits)`` onto ``ctx.deps.rag.max_score``.

    req: faq-rag-009, faq-rag-016
    """

    # Raw chunk text returned to the faq_agent as grounding context.
    text: str

    # Cosine similarity (pure cosine) or combined cosine + keyword score (hybrid).
    # Higher is better; threshold is ``similarity_min``.
    score: float

    # Foreign key to the parent Document row (used by the validator for logging).
    document_id: int


def _build_cosine_stmt(qvec: list[float], k: int) -> Any:
    """Return the pure-cosine pgvector SELECT statement (default path).

    Selects ``(text, document_id, distance)`` ordered by cosine distance ASC
    (lowest distance = highest similarity first).  The caller converts
    ``distance → similarity`` via ``1 - distance``.

    req: faq-rag-009, faq-rag-004
    """
    distance_col = DocumentChunk.embedding.cosine_distance(qvec)  # type: ignore[attr-defined]
    return (
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


def _build_hybrid_stmt(qvec: list[float], query_text: str, k: int) -> Any:
    """Return a SELECT statement ordering by combined cosine + keyword score.

    Score formula
    -------------
    combined_score = ALPHA * cosine_sim + (1 - ALPHA) * ts_rank_score

    Where:
        ALPHA          = 0.7   (see ``_HYBRID_ALPHA``)
        cosine_sim     = 1 - (embedding <=> qvec)
                         pgvector cosine distance converted to similarity; ∈ [0, 1].
        ts_rank_score  = ts_rank(
                             to_tsvector('english', chunk.text),
                             plainto_tsquery('english', query)
                         )
                         Postgres built-in full-text ranking function; ∈ [0, 1].

    Both components are in [0, 1], so combined_score ∈ [0, 1] and is directly
    comparable to the ``similarity_min`` threshold used in the pure cosine path.

    The cosine component captures semantic similarity (meaning proximity);
    the ts_rank component captures lexical overlap (exact / stemmed term matches).
    Combining them with a 70/30 weight improves recall for queries that contain
    domain-specific terminology present in the corpus.

    The ORDER BY repeats the raw expression (not the label) to ensure
    dialect-agnostic rendering.

    req: faq-rag-016
    """
    distance_col = DocumentChunk.embedding.cosine_distance(qvec)  # type: ignore[attr-defined]

    # cosine_sim ∈ [0, 1]: uses SQLAlchemy ColumnElement.__rsub__ at runtime.
    cosine_sim = 1.0 - distance_col

    # Postgres built-in full-text keyword score ∈ [0, 1].
    kw_score = func.ts_rank(
        func.to_tsvector("english", DocumentChunk.text),
        func.plainto_tsquery("english", query_text),
    )

    # Weighted sum: 0.7 * cosine_sim + 0.3 * kw_score.
    # cosine_sim is Any (derived from the pgvector attr-defined ignore above);
    # Python float * Any is handled at runtime via SQLAlchemy ColumnOperators.
    # combined_score in [0, 1].
    combined_score = _HYBRID_ALPHA * cosine_sim + (1.0 - _HYBRID_ALPHA) * kw_score

    return (
        select(  # type: ignore[call-overload]
            DocumentChunk.text,
            DocumentChunk.document_id,
            combined_score.label("score"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.status == "ready")
        .order_by(combined_score.desc())
        .limit(k)
    )


async def retrieve(
    db: AsyncSession,
    query: str,
    embedder: EmbeddingService,
    *,
    k: int,
    similarity_min: float,
    hybrid: bool = False,
) -> list[Hit]:
    """Return the top-k relevant DocumentChunk hits for ``query``.

    **Default mode** (``hybrid=False``): pure pgvector cosine ordering via the
    HNSW index.  This path is byte-for-byte identical to the pre-Task-10 behaviour.

    **Hybrid mode** (``hybrid=True``): combines cosine similarity with a Postgres
    full-text keyword score (``ts_rank``) before ranking.  The caller reads
    ``settings.hybrid_retrieval`` and passes it as ``hybrid``.  See
    ``_build_hybrid_stmt`` for the exact weighted-sum formula.  Default off
    (req: faq-rag-016).

    Only chunks whose parent ``Document`` has ``status == "ready"`` are queried.
    Hits whose score falls below ``similarity_min`` are silently dropped.

    pgvector distance convention (pure cosine path)
    ------------------------------------------------
    ``<=>`` returns cosine DISTANCE in [0, 2] for normalised vectors; real hits
    fall in [0, 1].  Cosine SIMILARITY = 1 - distance.  A hit requires:
        distance ≤ 1 - similarity_min

    Args:
        db:             Async SQLAlchemy session (injected from ``AgentDeps``).
        query:          The user's question / search string.
        embedder:       ``EmbeddingService`` instance; supplies ``embed_query``.
        k:              Maximum rows to fetch before threshold filtering.
        similarity_min: Minimum score (inclusive) to accept a chunk.
                        Chunks below this threshold are silently dropped.
        hybrid:         When True, fuse cosine with Postgres ts_rank keyword score
                        before ranking.  Read from ``settings.hybrid_retrieval``
                        at the call site.  Default False (req: faq-rag-016).

    Returns:
        List of :class:`Hit` ordered by score descending (highest first).
        An empty list when no chunk reaches ``similarity_min`` — the
        anti-hallucination path (req: faq-rag-011).

    Raises:
        EmbeddingError: Propagated when ``embedder.embed_query`` fails.  The
                        caller is responsible for degrading
                        (``needs_review=True``, lower ``confidence_score``).

    req: faq-rag-009, faq-rag-004, faq-rag-016
    Design contract: specs/faq-rag/design.md §2.4
    """
    # ------------------------------------------------------------------
    # Step 1: Embed the query.
    # EmbeddingError propagates — the caller must catch and degrade.
    # req: faq-rag-009
    # ------------------------------------------------------------------
    qvec: list[float] = await embedder.embed_query(query)

    # ------------------------------------------------------------------
    # Step 2: Build and execute the retrieval SQL.
    #
    # hybrid=False (default) — pure pgvector cosine HNSW path (req: faq-rag-009).
    #   Row shape: (text, document_id, distance).
    #   Caller converts: similarity = 1 - distance.
    #
    # hybrid=True — combined cosine + ts_rank path (req: faq-rag-016).
    #   Row shape: (text, document_id, score).
    #   score is the combined weighted sum ∈ [0, 1]; no conversion needed.
    #
    # Both JOINs filter Document.status == "ready" (req: faq-rag-004).
    # ------------------------------------------------------------------
    hits: list[Hit]

    if hybrid:
        # Hybrid: combined cosine + keyword score.
        # See _build_hybrid_stmt for the score formula.
        # req: faq-rag-016
        hybrid_stmt = _build_hybrid_stmt(qvec, query, k)
        hybrid_result = await db.execute(hybrid_stmt)
        hybrid_rows = hybrid_result.all()

        hits = [
            Hit(
                text=str(r.text),
                score=float(r.score),
                document_id=int(r.document_id),
            )
            for r in hybrid_rows
            if float(r.score) >= similarity_min
        ]
    else:
        # Pure cosine (default): pgvector HNSW cosine distance.
        # req: faq-rag-009, faq-rag-004
        cosine_stmt = _build_cosine_stmt(qvec, k)
        cosine_result = await db.execute(cosine_stmt)
        cosine_rows = cosine_result.all()

        hits = []
        for row in cosine_rows:
            similarity: float = 1.0 - float(row.distance)
            if similarity >= similarity_min:
                hits.append(
                    Hit(
                        text=str(row.text),
                        score=similarity,
                        document_id=int(row.document_id),
                    )
                )

    return hits
