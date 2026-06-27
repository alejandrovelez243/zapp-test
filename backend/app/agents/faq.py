"""FAQ-RAG agent — answers ONLY from retrieved document chunks.

The ``faq_agent`` is constructed lazily via ``get_faq_agent()`` (``lru_cache``,
mirrors ``get_orchestrator``) so importing this module requires NO gateway key.

The single registered tool ``_retrieve_chunks_impl`` calls the pgvector cosine
retrieval and records the retrieval signal on ``ctx.deps.rag`` (``hit_count`` +
``max_score``).  The orchestrator's output_validator reads these fields after the
``ask_faq`` tool returns and uses them to damp ``confidence_score`` and set
``needs_review=True`` when retrieval is empty or below threshold.

Anti-hallucination path: when ``retrieve`` returns an empty list (no chunk meets
``similarity_min``), the tool returns ``[]``.  The agent's instructions then say
"I don't have that information" — it never invents an answer.

Requirements:
  faq-rag-010 — grounded instructions (answer ONLY from retrieved chunks)
  faq-rag-011 — empty-retrieval path: deps.rag signal → validator dampens
  faq-rag-012 — answer in the session active_lang
  faq-rag-013 — NEVER cite the source document

Design contract: specs/faq-rag/design.md §2.5
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_ai import Agent, RunContext

from app.config import get_settings
from app.deps import AgentDeps
from app.rag.embeddings import EmbeddingService
from app.rag.retrieve import Hit, retrieve

# ---------------------------------------------------------------------------
# Static instructions — cached by the model (anthropic_cache_instructions).
# Role → Objective → Capabilities → Operating Instructions → Guardrails.
# req: faq-rag-010, faq-rag-012, faq-rag-013
# ---------------------------------------------------------------------------
_FAQ_INSTRUCTIONS: str = (
    "Answer ONLY from the retrieved chunks; "
    "if none are relevant, say you do not have that information; "
    "reply in the session active_lang; "
    "NEVER cite the source."
)


async def _retrieve_chunks_impl(ctx: RunContext[AgentDeps], query: str) -> list[str]:
    """Cosine-retrieve the top-k most relevant document chunks for ``query``.

    Steps
    -----
    1. Call ``retrieve()`` with the session's ``AsyncSession``, the user query, and a
       freshly constructed ``EmbeddingService`` (lazy — no key touched at call time
       until the first embed call inside ``retrieve``).
    2. Record the retrieval signal on ``ctx.deps.rag``:
       - ``hit_count``: total qualifying hits (0 on empty retrieval).
       - ``max_score``: cosine similarity of the top-ranked hit (``None`` when empty).
    3. Return the chunk texts as a plain ``list[str]`` — only text, no document_id
       or score (the "NEVER cite" constraint strips metadata before the model sees it).
       An empty list on zero qualifying hits triggers the anti-hallucination path.

    The ``EmbeddingService()`` constructor is lazy: no key is read until the first
    ``embed_query`` call inside ``retrieve``.  Importing this module or registering
    the tool both happen without a gateway key in the environment.

    Args:
        ctx:   ``RunContext`` carrying ``AgentDeps`` (DB session, rag signal, …).
        query: The user question to embed and search against the pgvector index.

    Returns:
        Chunk texts (``list[str]``) ordered by cosine similarity descending.
        Empty list when no chunk meets ``rag_similarity_min``.

    req: faq-rag-009 (cosine retrieval), faq-rag-011 (signal + anti-hallucination),
         faq-rag-012 (active_lang), faq-rag-013 (no citation)
    Design contract: specs/faq-rag/design.md §2.5
    """
    settings = get_settings()
    hits: list[Hit] = await retrieve(
        ctx.deps.session,
        query,
        EmbeddingService(),
        k=settings.rag_top_k,
        similarity_min=settings.rag_similarity_min,
    )

    # Record retrieval signal — orchestrator output_validator reads these.
    # req: faq-rag-011 (producer side)
    ctx.deps.rag.hit_count = len(hits)
    ctx.deps.rag.max_score = hits[0].score if hits else None

    # Strip metadata — return only text so the model never has a score or doc id
    # to cite. req: faq-rag-013
    return [hit.text for hit in hits]


@lru_cache(maxsize=1)
def get_faq_agent() -> Agent[AgentDeps, str]:
    """Construct and return the cached FAQ-RAG agent (lazy factory).

    Mirrors ``get_orchestrator``: importing this module requires NO gateway key.
    The first call builds the ``Agent``, registers ``_retrieve_chunks_impl`` as a
    tool, and caches the result for the process lifetime.

    The agent uses ``output_type=str`` (plain text answer) rather than
    ``TurnOutput`` — the orchestrator wraps it as an agent-as-tool
    (``ask_faq``) and assembles the full ``TurnOutput`` contract itself.

    Calling ``agent.tool(fn)`` is equivalent to decorating ``fn`` with
    ``@agent.tool`` — both append to the agent's internal tool registry.  The
    lazy pattern (register inside the factory rather than at module scope) keeps
    the module import key-free, mirroring the instructions/validator registration
    in ``get_orchestrator``.

    req: faq-rag-010, faq-rag-011, faq-rag-012, faq-rag-013
    Design contract: specs/faq-rag/design.md §2.5
    """
    agent: Agent[AgentDeps, str] = Agent(
        get_settings().worker_model,
        deps_type=AgentDeps,
        output_type=str,
        instructions=_FAQ_INSTRUCTIONS,
        retries=2,
    )
    # Register the retrieval tool.  Equivalent to @agent.tool on _retrieve_chunks_impl.
    # req: faq-rag-009, faq-rag-011
    agent.tool(_retrieve_chunks_impl)
    return agent
