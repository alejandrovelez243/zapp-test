/**
 * lib/api.ts
 *
 * Transport layer for chat turns. The only exported function, `postTurn`, resolves
 * to either a validated TurnOutput or a typed ApiError — it NEVER throws to the
 * view layer (req frontend-shell-006). This keeps error-handling logic out of
 * components and in one well-tested place.
 *
 * The request goes to same-origin `/api/chat`, which Next.js rewrites to
 * `${NEXT_PUBLIC_API_URL}/chat` (no CORS needed — task 3 wired the rewrite).
 *
 * Traces: frontend-shell-003 (POST session_id + message),
 *         frontend-shell-004 (parse TurnOutput),
 *         frontend-shell-006 (non-2xx / network / malformed → ApiError)
 */

import { isTurnOutput, type TurnOutput } from "./contract";

// ---------------------------------------------------------------------------
// ApiError — discriminated error union
//
// kind breakdown:
//   'network'   — fetch() itself threw (offline, DNS failure, CORS, timeout)
//   'http'      — server replied with a non-2xx status
//   'malformed' — 2xx but body is not valid JSON or fails isTurnOutput
//
// The `ok: false` discriminant lets callers narrow with a simple `ok` check:
//   const result = await postTurn(...);
//   if (!isApiError(result)) { /* TurnOutput */ } else { /* ApiError */ }
// ---------------------------------------------------------------------------

export interface ApiError {
  ok: false;
  kind: "network" | "http" | "malformed";
  /** HTTP status code — present for 'http' and 'malformed' (where we got a response). */
  status?: number;
  message: string;
}

/**
 * Narrows a postTurn result to ApiError.
 * Use this instead of `'ok' in result` to keep call sites readable.
 */
export function isApiError(x: TurnOutput | ApiError): x is ApiError {
  return "ok" in x && (x as ApiError).ok === false;
}

// ---------------------------------------------------------------------------
// postTurn — the single entry point for sending a chat turn
// ---------------------------------------------------------------------------

/**
 * POST `/api/chat` with `{ session_id, message }` and return the parsed
 * TurnOutput. If anything goes wrong at the network, HTTP, or parsing layer,
 * returns a typed ApiError instead of throwing.
 *
 * @param sessionId  Stable per-tab anonymous id from lib/session.ts
 * @param message    The student's raw message text
 */
export async function postTurn(
  sessionId: string,
  message: string
): Promise<TurnOutput | ApiError> {
  // ---- 1. Network fetch --------------------------------------------------
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
  } catch (err) {
    // fetch() threw — no HTTP response available
    return {
      ok: false,
      kind: "network",
      message: err instanceof Error ? err.message : "Network error",
    };
  }

  // ---- 2. HTTP status check ----------------------------------------------
  if (!response.ok) {
    return {
      ok: false,
      kind: "http",
      status: response.status,
      message: `Server responded with ${response.status}`,
    };
  }

  // ---- 3. JSON parse -----------------------------------------------------
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return {
      ok: false,
      kind: "malformed",
      status: response.status,
      message: "Response body is not valid JSON",
    };
  }

  // ---- 4. Contract shape guard -------------------------------------------
  if (!isTurnOutput(body)) {
    return {
      ok: false,
      kind: "malformed",
      status: response.status,
      message: "Response body does not match the per-turn contract schema",
    };
  }

  return body;
}
