# FAQ-RAG Requirements

## Summary

A retrieval-augmented FAQ agent that answers student questions grounded in **uploaded course
documents**. Admins upload documents (PDF / Markdown / TXT) which are chunked, embedded with
**OpenAI `text-embedding-3-small` via the Pydantic AI Gateway** (the SAME single gateway token — no
separate key), and stored as **pgvector** vectors (HNSW, cosine).
At query time the FAQ-RAG agent (an orchestrator tool) retrieves the top-k most similar chunks and
answers **grounded only in them**, in the session `active_lang`. Grounding is **silent** (no source
citation in the reply). Empty/low retrieval → no hallucination + `needs_review` + lower
`confidence_score`.

## Persona & job-to-be-done

As a prospective/current student, I want answers to my questions about the courses drawn from the
school's actual documents, so I can trust them. As an admin, I want to upload, list, update, and
delete the document corpus, so the FAQ stays current.

## In / Out of scope

In scope: admin document lifecycle (upload PDF/MD/TXT → BACKGROUND ingestion → list → delete; update =
re-ingest + atomic swap); chunking + OpenAI `text-embedding-3-small` embeddings via the gateway → pgvector (HNSW, cosine); the
FAQ-RAG agent run as an orchestrator tool (top-k cosine retrieval → grounded answer in `active_lang`);
silent grounding (no citation); anti-hallucination on empty/low retrieval; multilingual (docs in any
language, answer in `active_lang`); admin-token auth for management, anonymous sessions for queries.

Out of scope (own specs / deferred): the orchestrator routing itself (exists); the EVENTS agent;
guardrail content (`guardrails`); the eval runner (`evaluation`); **PageIndex** (deferred upgrade
path); a **reranker** (deferred); source **citations** (chosen: silent grounding).

## Config flags & values

- `hybrid_retrieval` (flag, default **off**): off = pure pgvector cosine top-k; on = combine cosine
  with keyword/BM25 scores before ranking.
- Config values (resolved in design): `rag_top_k`, `rag_similarity_min` (no-match threshold),
  `embedding_model` (`gateway/openai:text-embedding-3-small`), `embedding_dim` (1536, fixed pgvector column dimension),
  `chunk_size`/`chunk_overlap`.

## User Stories

- As a student, I want FAQ answers grounded in the school's documents, so I get trustworthy information.
- As a student asking something not in the docs, I want an honest "I don't have that" rather than a made-up answer.
- As an admin, I want to upload/list/update/delete documents behind my token, so the corpus stays correct.

## Acceptance Criteria

1. WHERE the request carries a valid admin token THE SYSTEM SHALL accept a document upload in PDF, Markdown, or TXT.   <!-- eval: faq-rag-001 -->
2. IF a document-management request lacks a valid admin token THEN THE SYSTEM SHALL reject it (401/403) AND not ingest or mutate the corpus.   <!-- eval: faq-rag-002 -->
3. WHEN a document is uploaded THE SYSTEM SHALL ingest it in a BACKGROUND job (never inline in the request): extract text, chunk it, embed each chunk, and store chunks + vectors.   <!-- eval: faq-rag-003 -->
4. WHILE a document's ingestion is still running THE SYSTEM SHALL exclude that document's chunks from retrieval.   <!-- eval: faq-rag-004 -->
5. THE SYSTEM SHALL embed chunks with the configured embedding model (OpenAI `text-embedding-3-small`) via the gateway and store fixed-dimension (1536) vectors in a pgvector column with an HNSW index.   <!-- eval: faq-rag-005 -->
6. WHEN an admin lists documents THE SYSTEM SHALL return each document's id, name, and ingestion status.   <!-- eval: faq-rag-006 -->
7. WHEN an admin deletes a document THE SYSTEM SHALL remove the document and all its chunks/vectors from retrieval.   <!-- eval: faq-rag-007 -->
8. WHEN an admin re-uploads/updates a document THE SYSTEM SHALL re-ingest into new rows and atomically swap, then delete the old rows (ingested documents are immutable).   <!-- eval: faq-rag-008 -->
9. WHEN a user asks a question THE SYSTEM SHALL retrieve the top-k most similar chunks by pgvector cosine similarity.   <!-- eval: faq-rag-009 -->
10. WHEN relevant chunks are retrieved THE SYSTEM SHALL answer grounded ONLY in those chunks, in the session `active_lang`.   <!-- eval: faq-rag-010 -->
11. IF retrieval returns no chunk above the configured similarity threshold THEN THE SYSTEM SHALL NOT invent an answer, SHALL state it does not have that information, AND SHALL set `needs_review=true` and lower `confidence_score`.   <!-- eval: faq-rag-011 -->
12. THE SYSTEM SHALL answer in the session `active_lang` (ES/EN/PT) regardless of the source document's language; an unsupported language falls back to the configured fallback AND sets `needs_review=true`.   <!-- eval: faq-rag-012 -->
13. THE SYSTEM SHALL ground answers silently — it SHALL NOT include a source citation in the `reply`.   <!-- eval: faq-rag-013 -->
14. THE SYSTEM SHALL run the FAQ-RAG agent as an orchestrator tool, forwarding `deps` and `usage` (shared `RunUsage`) and honoring the orchestrator's `UsageLimits`.   <!-- eval: faq-rag-014 -->
15. WHEN retrieval is low-confidence or partial THE SYSTEM SHALL lower `confidence_score` accordingly.   <!-- eval: faq-rag-015 -->
16. WHERE `hybrid_retrieval` is enabled THE SYSTEM SHALL combine pgvector cosine scores with keyword scores before ranking chunks.   <!-- eval: faq-rag-016 -->
17. IF the embedding gateway call fails during a query THEN THE SYSTEM SHALL degrade to a valid nine-field contract with `needs_review=true` (never a 5xx to the user).   <!-- eval: faq-rag-017 -->
18. IF ingestion of a document fails THEN THE SYSTEM SHALL mark that document's status as failed AND keep the rest of the corpus usable.   <!-- eval: faq-rag-018 -->

## Case-id map

`faq-rag-001..018` map 1:1 to eval `Case`s of the same id: happy (grounded answer), multilingual
(doc lang ≠ active_lang), anti-hallucination (out-of-corpus question → "I don't have that" +
`needs_review`), admin-auth (reject without token), and low-retrieval / degraded paths. Ids are
append-only. Retrieval-quality Cases assert on `reply` grounding + `needs_review`/`confidence_score`.

## Non-functional / contract

- **Writes** these per-turn contract fields: `reply` (grounded answer in `active_lang`),
  `confidence_score` (reflecting retrieval confidence), `needs_review` (empty/low retrieval, embedding
  error, or unsupported-language fallback). **Reads** `active_lang` (owned by `multilingual`).
- Auth: document upload/list/update/delete require the **admin token**; student queries are anonymous.
- Languages: answers in **ES / EN / PT** (the session `active_lang`) regardless of document language;
  unsupported → fallback + `needs_review=true`.
- Anti-hallucination: never answer beyond the retrieved chunks; empty/low retrieval → honest "no
  information" + `needs_review` + damped `confidence_score`.
- Data lifecycle: ingestion is a BACKGROUND job (never inline); ingested documents are immutable
  (update = re-ingest + atomic swap + delete old). OpenAI `text-embedding-3-small` embeddings via the gateway (one token); fixed-dimension
  pgvector column with an HNSW cosine index. **PageIndex** and a **reranker** are deferred.
