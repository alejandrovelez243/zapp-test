# FAQ-RAG Tasks

Ordered, dependency-aware plan for `faq-rag` (pgvector RAG over admin-uploaded docs; Gemini embeddings;
grounded answers; anti-hallucination). Each task = one specialist delegation + one commit. Traceability:
`— _req: <ids> — owner: <specialist>_`. Prereqs (deps, config, models/migration, embeddings) precede the
ingest/retrieve/agent consumers. Drive task-by-task via `/implement faq-rag`.

> Embeddings = **Gemini via the gateway** (`text-embedding-004` @ 768 dims, fixed pgvector column);
> transport confirmed at integration (gateway embeddings endpoint vs `google-genai` client — isolated in
> `EmbeddingService`). Ingestion is a BACKGROUND job. Empty/low retrieval → no hallucination +
> `needs_review` + `confidence_score`↓. The offline eval (task 12) needs a seeded corpus + gateway key.

## Tasks

- [x] 1. Add dependencies via `uv add`: `pgvector`, `pypdf` (PDF extraction), and the Gemini embeddings client (`google-genai`) — do NOT hand-edit `pyproject.toml`/`uv.lock`. — _req: faq-rag-005 — owner: devops-engineer_

- [x] 2. Add FAQ-RAG config to `app/config.py` `Settings`: `hybrid_retrieval: bool = False`, `rag_top_k: int = 5`, `rag_similarity_min: float`, `embedding_model` (Gemini id), `embedding_dim: int = 768`, `chunk_size`, `chunk_overlap`. — _req: faq-rag-005, faq-rag-009, faq-rag-016 — owner: backend-engineer_

- [x] 3. Implement `app/rag/models.py` — `Document` (id/name/content_type/status/error/timestamps) + `DocumentChunk` (document_id FK, ordinal, text, `embedding: Vector(embedding_dim)`); Alembic migration `0005` creating both tables + an HNSW index on `embedding` with `vector_cosine_ops` (naive-UTC timestamps). — _req: faq-rag-005 — owner: backend-engineer_

- [x] 4. Implement `app/rag/embeddings.py` — `EmbeddingService.embed(texts) -> list[list[float]]` calling the configured Gemini model via the gateway (batched, timeout-bounded, `logfire.span`); raises a typed error callers handle. — _req: faq-rag-005, faq-rag-017 — owner: backend-engineer_

- [x] 5. Implement `app/rag/ingest.py` — background ingestion: `extract_text` (pypdf for PDF, decode for md/txt) → `chunk` → `EmbeddingService.embed` → insert `DocumentChunk` rows; set `Document.status` pending→ingesting→ready; on failure → `status="failed"` + `error`, corpus stays usable; `reingest_and_swap` (re-ingest new rows + atomic swap + delete old). — _req: faq-rag-003, faq-rag-004, faq-rag-008, faq-rag-018 — owner: backend-engineer_

- [x] 6. Implement `app/rag/retrieve.py` — `retrieve(db, query, *, k, similarity_min) -> list[Hit]`: embed query → pgvector cosine top-k `ORDER BY embedding <=> :qvec` filtered to `status=="ready"`; drop hits below `similarity_min`. — _req: faq-rag-009, faq-rag-004 — owner: backend-engineer_

- [x] 7. Implement `app/agents/faq.py` — `faq_agent` (worker model, instructions: answer ONLY from retrieved chunks, in `active_lang`, never cite; say "no info" when none) + `@faq_agent.tool retrieve_chunks` (calls retrieve, records top score + hit count on `ctx.deps.rag`, returns chunk texts / empty on no-hit). — _req: faq-rag-010, faq-rag-011, faq-rag-012, faq-rag-013 — owner: backend-engineer_

- [ ] 8. Add `AgentDeps.rag: RagSignal` (`app/deps.py`) and wire the orchestrator (`app/agents/orchestrator.py`): `@orchestrator.tool ask_faq` (forwards `deps`+`usage`, capped by `UsageLimits`) + a reconciliation step that, when `deps.rag` shows empty/low retrieval, lowers `confidence_score` and sets `needs_review=true`. — _req: faq-rag-011, faq-rag-014, faq-rag-015 — owner: backend-engineer_

- [x] 9. Implement `app/api/documents.py` — admin-token-gated endpoints: `POST /documents` (validate pdf/md/txt, create `Document(status=pending)`, schedule background ingest, 202), `GET /documents` (list id/name/status), `DELETE /documents/{id}`, `PUT /documents/{id}` (reingest_and_swap); missing/invalid token → 401/403 + no mutation. — _req: faq-rag-001, faq-rag-002, faq-rag-006, faq-rag-007, faq-rag-008 — owner: backend-engineer_

- [x] 10. (Tier-3 flag) Implement the `hybrid_retrieval` branch in `retrieve.py` — combine pgvector cosine with a keyword score (Postgres `ILIKE`/`ts_rank`) before ranking; default off. — _req: faq-rag-016 — owner: backend-engineer_

- [ ] 11. Add tests: models + migration (offline SQL); `EmbeddingService` (mocked gateway); `ingest` (mocked embed, status transitions, failure → failed); `retrieve` (cosine ordering + threshold, status filter; hybrid path); `faq_agent` (TestModel + mocked retrieval: grounded answer, empty → "no info"); orchestrator `ask_faq` + RAG reconcile (empty → confidence↓ + needs_review); admin endpoints (auth reject, upload schedules ingest, delete). — _req: faq-rag-001..faq-rag-018 — owner: backend-engineer_

- [ ] 12. Add eval Cases + verification: seed a tiny test corpus, add `faq-rag` eval Cases (grounded happy, anti-hallucination out-of-corpus → needs_review, multilingual doc≠active_lang, admin-auth reject, low-retrieval) to `backend/evals/datasets/`; run the suite to confirm grounding + anti-hallucination behavior. (Real run needs `PYDANTIC_AI_GATEWAY_API_KEY` + embeddings; the deterministic retrieval/reconcile logic is unit-verifiable without it.) — _req: faq-rag-001..faq-rag-018 — owner: eval-engineer_

## Coverage

| Req | Tasks |
|---|---|
| faq-rag-001 | 9, 11, 12 |
| faq-rag-002 | 9, 11, 12 |
| faq-rag-003 | 5, 11 |
| faq-rag-004 | 5, 6, 11 |
| faq-rag-005 | 1, 2, 3, 4, 11 |
| faq-rag-006 | 9, 11 |
| faq-rag-007 | 9, 11 |
| faq-rag-008 | 5, 9, 11 |
| faq-rag-009 | 2, 6, 11 |
| faq-rag-010 | 7, 11, 12 |
| faq-rag-011 | 7, 8, 11, 12 |
| faq-rag-012 | 7, 11, 12 |
| faq-rag-013 | 7, 11 |
| faq-rag-014 | 8, 11 |
| faq-rag-015 | 8, 11 |
| faq-rag-016 | 2, 10, 11 |
| faq-rag-017 | 4, 8, 11 |
| faq-rag-018 | 5, 11 |

Every requirement id (`faq-rag-001..018`) appears in at least one task. Verification = pytest (task 11)
+ the eval grounding/anti-hallucination Cases (task 12) + CI.
