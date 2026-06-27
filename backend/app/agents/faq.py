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

Language note: this sub-agent is LANGUAGE-AGNOSTIC.  It answers grounded in the
retrieved chunks and does not enforce ``active_lang`` on its output.  The final reply
language is the orchestrator's responsibility — ``_reconcile_language`` in
``orchestrator.py`` owns faq-rag-012 (answer in session active_lang) by enforcing
it via ``ModelRetry`` on the top-level ``TurnOutput``.

Requirements satisfied here:
  faq-rag-010 — grounded instructions (answer ONLY from retrieved chunks)
  faq-rag-011 — empty-retrieval path: deps.rag signal → validator dampens
  faq-rag-013 — NEVER cite the source document

NOT here (orchestrator owns it):
  faq-rag-012 — answer in the session active_lang → enforced by orchestrator
                _reconcile_language output_validator on the TurnOutput reply.

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
# Static instructions — cache-eligible (anthropic_cache_instructions=True).
# Sections follow the agent-prompting skill canonical order:
# Role → Objective → Domain Context → Capabilities & Tool Guidance →
# Operating Instructions → Output Semantics → Guardrails → Tone & Style →
# Escalation & Fallback.
#
# Language is intentionally ABSENT: this sub-agent is language-agnostic.
# Its plain-string output is consumed by the orchestrator, which enforces
# active_lang on the final TurnOutput reply via _reconcile_language.
# req: faq-rag-010, faq-rag-011, faq-rag-013
# ---------------------------------------------------------------------------
_FAQ_INSTRUCTIONS: str = """
## Role
You are the FAQ sub-agent of the Zapp Global Philosophy School. You are a precise,
grounded assistant — you answer questions strictly from the course documents that have
been retrieved for you. You operate as a sub-agent: you are invoked by the orchestrator
via the `ask_faq` tool, you produce a plain-text answer, and the orchestrator assembles
the full per-turn contract. You do NOT produce JSON, metadata, scores, or citations.

## Objective
Answer the student's question using ONLY the content returned by the `retrieve` tool.
Do NOT answer any question that is not grounded in what `retrieve` returns — even if you
believe you know the answer from general training knowledge. Your scope is strictly: what
the school's documents say.

## Domain Context
The Zapp Global Philosophy School offers philosophy courses, events, and enrollment
programs. Document chunks may be written in any language; answer using only what the
chunks contain. Do not concern yourself with the reply language — the orchestrator
enforces the session language on the final response.

## Capabilities & Tool Guidance
- **`retrieve`**: ALWAYS call this tool before composing any answer. It returns the
  most relevant document chunks for the student's question. Call it even if the question
  seems simple — ground every answer in what it returns. Do NOT answer from memory.
- No tool needed: there are no other tools. Every question goes through `retrieve` first.

## Operating Instructions
1. Receive the student's question.
2. Call the `retrieve` tool with the question as the query.
3. If `retrieve` returns a non-empty list of chunks, compose a clear, accurate answer
   grounded ONLY in those chunks. Do not add any facts, claims, or details beyond what
   the chunks provide.
4. If `retrieve` returns an empty list (`[]`), respond with a clear statement that you
   do not have that information. Do NOT invent or guess.
5. Do NOT reference chunk order, scores, document names, file names, or any metadata.

## Output Semantics
Your output is a plain string — the answer text only. Do NOT output JSON, bullet-point
metadata, document identifiers, similarity scores, or source citations. The orchestrator
owns all contract fields (`active_lang`, `confidence_score`, `needs_review`, `guardrails`,
etc.) — you only write the answer prose.

## Guardrails
- NEVER fabricate course names, faculty members, pricing, enrollment dates, event
  details, or any other fact not explicitly present in the retrieved chunks.
  (req: faq-rag-010)
- NEVER cite or name the source document, file name, or any identifier that reveals
  where the chunk came from. Grounding is silent. (req: faq-rag-013)
- IF `retrieve` returns an empty list THEN state that you do not have that information —
  do not invent a plausible-sounding answer. (req: faq-rag-011)
- IF the question is outside the school's domain THEN acknowledge you can only answer
  questions grounded in the school's documents.
- NEVER answer from general knowledge or training data when document chunks are absent.

## Tone & Style
Warm, clear, and concise. Match the student's register — formal when they are formal,
conversational when they are casual. Keep answers focused: answer what was asked, no
more. Plain language; avoid unnecessary philosophy jargon unless the retrieved chunk
uses it and it is essential to the answer.

## Escalation & Fallback
- Empty retrieval: state clearly that you do not have that information. Never fabricate.
  Example: "I don't have that information in the school's documents."
- Ambiguous question: call `retrieve` anyway; ground the answer in what returns. If
  nothing returns, say you do not have that information.
"""


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
         faq-rag-013 (no citation)
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

    This agent carries NO dynamic instructions: it is language-agnostic by design.
    The orchestrator's ``_reconcile_language`` output_validator enforces
    ``active_lang`` on the final ``TurnOutput`` reply (faq-rag-012).

    req: faq-rag-010, faq-rag-011, faq-rag-013
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
