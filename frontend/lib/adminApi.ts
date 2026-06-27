/**
 * lib/adminApi.ts
 *
 * Transport layer for admin document management.  Mirrors the pattern of
 * lib/api.ts: every call returns a discriminated union (success | AdminApiError)
 * and never throws to the view layer.
 *
 * All four document endpoints are reached via the same-origin Next.js rewrite:
 *   /api/documents → ${NEXT_PUBLIC_API_URL}/documents
 * so no CORS headers are needed in the browser.
 *
 * Auth: every call sends the admin token as "X-Admin-Token".  A 401 means the
 * token is absent (shouldn't happen here — we gate the UI), and 403 means the
 * token is wrong.  Both are surfaced to the caller via AdminApiError so the UI
 * can clear the token and prompt again.
 *
 * req: faq-rag-001 (POST /documents upload)
 * req: faq-rag-006 (GET /documents list)
 * req: faq-rag-007 (DELETE /documents/{id})
 * req: faq-rag-008 (PUT /documents/{id} re-ingest)
 * req: faq-rag-002 (401/403 surfaces to caller)
 */

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

/**
 * Document ingestion lifecycle states.
 * req: admin-console-011, admin-console-015
 */
export type DocStatus = 'pending' | 'ingesting' | 'ready' | 'failed';

/** One row from GET /documents. */
export interface DocumentSummary {
  id: number;
  name: string;
  status: DocStatus;
}

/** Returned by POST /documents and PUT /documents/{id} on success (202). */
export interface DocumentCreated {
  id: number;
}

/** Discriminated error union — callers narrow with `isAdminApiError()`. */
export interface AdminApiError {
  ok: false;
  /**
   * 'auth'     — 401 or 403: token missing or wrong
   * 'notfound' — 404: document id does not exist
   * 'invalid'  — 422: bad file type or other validation failure
   * 'http'     — any other non-2xx status
   * 'network'  — fetch threw (offline / DNS / CORS)
   * 'malformed'— 2xx but body cannot be parsed
   */
  kind: "auth" | "notfound" | "invalid" | "http" | "network" | "malformed";
  status?: number;
  message: string;
}

/** Narrows a result to AdminApiError. */
export function isAdminApiError(
  x: DocumentSummary[] | DocumentCreated | true | AdminApiError
): x is AdminApiError {
  return typeof x === "object" && x !== null && "ok" in x && (x as AdminApiError).ok === false;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Map a non-2xx HTTP status to the appropriate AdminApiError kind. */
function httpErrorKind(status: number): AdminApiError["kind"] {
  if (status === 401 || status === 403) return "auth";
  if (status === 404) return "notfound";
  if (status === 422) return "invalid";
  return "http";
}

/**
 * Build auth headers shared by all calls.
 * The token is kept in component state / sessionStorage — never in NEXT_PUBLIC_*.
 */
function authHeaders(token: string): Record<string, string> {
  return { "X-Admin-Token": token };
}

/** Perform a fetch and return a Response, or an AdminApiError on network failure. */
async function safeFetch(
  input: RequestInfo,
  init?: RequestInit
): Promise<Response | AdminApiError> {
  try {
    return await fetch(input, init);
  } catch (err) {
    return {
      ok: false,
      kind: "network",
      message: err instanceof Error ? err.message : "Network error",
    };
  }
}

// ---------------------------------------------------------------------------
// GET /documents — list all documents
// ---------------------------------------------------------------------------

/**
 * Fetch the current document list.  Returns the array on success or an
 * AdminApiError on any failure.
 *
 * req: faq-rag-006
 */
export async function listDocuments(
  token: string
): Promise<DocumentSummary[] | AdminApiError> {
  const res = await safeFetch("/api/documents", {
    headers: authHeaders(token),
  });

  if ("ok" in res && res.ok === false) return res as AdminApiError;

  const response = res as Response;
  if (!response.ok) {
    return {
      ok: false,
      kind: httpErrorKind(response.status),
      status: response.status,
      message: `GET /documents returned ${response.status}`,
    };
  }

  try {
    const body: unknown = await response.json();
    if (!Array.isArray(body)) throw new Error("not an array");
    return body as DocumentSummary[];
  } catch {
    return {
      ok: false,
      kind: "malformed",
      status: response.status,
      message: "Response body is not a valid document list",
    };
  }
}

// ---------------------------------------------------------------------------
// POST /documents — upload a new document
// ---------------------------------------------------------------------------

/**
 * Upload a document file.  Returns {id} on 202 or an AdminApiError.
 * The backend schedules ingestion as a background job; the returned id can be
 * used to track status via GET /documents.
 *
 * req: faq-rag-001, faq-rag-003
 */
export async function uploadDocument(
  token: string,
  file: File
): Promise<DocumentCreated | AdminApiError> {
  const form = new FormData();
  form.append("file", file);

  const res = await safeFetch("/api/documents", {
    method: "POST",
    headers: authHeaders(token),
    body: form,
  });

  if ("ok" in res && res.ok === false) return res as AdminApiError;

  const response = res as Response;
  if (!response.ok) {
    // Surface server-provided detail if available (e.g. "Unsupported file type")
    let detail = `POST /documents returned ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore parse failure — keep the generic message
    }
    return {
      ok: false,
      kind: httpErrorKind(response.status),
      status: response.status,
      message: detail,
    };
  }

  try {
    const body = (await response.json()) as { id?: number };
    if (typeof body.id !== "number") throw new Error("missing id");
    return { id: body.id };
  } catch {
    return {
      ok: false,
      kind: "malformed",
      status: response.status,
      message: "Upload response did not include a document id",
    };
  }
}

// ---------------------------------------------------------------------------
// DELETE /documents/{id} — remove document and chunks
// ---------------------------------------------------------------------------

/**
 * Delete a document by id.  Returns `true` on 204 or an AdminApiError.
 *
 * req: faq-rag-007
 */
export async function deleteDocument(
  token: string,
  id: number
): Promise<true | AdminApiError> {
  const res = await safeFetch(`/api/documents/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });

  if ("ok" in res && res.ok === false) return res as AdminApiError;

  const response = res as Response;
  // 204 No Content is the success case
  if (response.status === 204) return true;
  if (response.ok) return true;

  return {
    ok: false,
    kind: httpErrorKind(response.status),
    status: response.status,
    message: `DELETE /documents/${id} returned ${response.status}`,
  };
}

// ---------------------------------------------------------------------------
// PUT /documents/{id} — replace document (re-ingest and atomic swap)
// ---------------------------------------------------------------------------

/**
 * Replace an existing document with a new file.  The backend re-ingests into
 * new rows and atomically swaps them, keeping the corpus queryable throughout.
 * Returns {id} on 202 or an AdminApiError.
 *
 * req: faq-rag-008
 */
export async function replaceDocument(
  token: string,
  id: number,
  file: File
): Promise<DocumentCreated | AdminApiError> {
  const form = new FormData();
  form.append("file", file);

  const res = await safeFetch(`/api/documents/${id}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: form,
  });

  if ("ok" in res && res.ok === false) return res as AdminApiError;

  const response = res as Response;
  if (!response.ok) {
    let detail = `PUT /documents/${id} returned ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore
    }
    return {
      ok: false,
      kind: httpErrorKind(response.status),
      status: response.status,
      message: detail,
    };
  }

  try {
    const body = (await response.json()) as { id?: number };
    if (typeof body.id !== "number") throw new Error("missing id");
    return { id: body.id };
  } catch {
    return {
      ok: false,
      kind: "malformed",
      status: response.status,
      message: "Replace response did not include a document id",
    };
  }
}
