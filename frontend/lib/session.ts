/**
 * lib/session.ts
 *
 * Provides a stable, anonymous per-tab session_id that is sent on every chat
 * request so the backend can replay multi-turn memory (req frontend-shell-002).
 *
 * Strategy:
 *   - On first call within a browser tab: generate with crypto.randomUUID() and
 *     store in sessionStorage under SESSION_KEY.
 *   - On subsequent calls (same tab, including page refresh): return the stored id.
 *   - SSR context (window/sessionStorage unavailable): return a fresh UUID that
 *     will not be persisted — the component must call getSessionId() on the client
 *     side (inside useEffect / client island) to get the stable value.
 *   - If sessionStorage access throws (privacy mode, security policy): fall back to
 *     an in-memory id for the lifetime of the module instance.
 *
 * Traces: frontend-shell-002 (anonymous session_id persisted, sent every turn)
 */

const SESSION_KEY = "zapp_session_id";

/**
 * In-memory fallback for environments where sessionStorage is inaccessible
 * (e.g. Safari ITP in strict mode). Scoped to the module — lives as long as
 * the JS bundle is loaded, which is long enough for one browser session.
 */
let memoryFallback: string | null = null;

/**
 * Returns the stable per-tab anonymous session_id.
 *
 * Call this from client-only code (inside "use client" components or useEffect)
 * to ensure sessionStorage is available. During SSR, a transient UUID is returned;
 * it is not the session id that will be sent with actual chat requests.
 */
export function getSessionId(): string {
  // Guard for SSR: window is not defined on the server.
  if (typeof window === "undefined") {
    return crypto.randomUUID();
  }

  try {
    const stored = sessionStorage.getItem(SESSION_KEY);
    if (stored !== null) return stored;

    const id = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, id);
    return id;
  } catch {
    // sessionStorage access denied (incognito, security policy, etc.).
    // Fall back to a module-scoped in-memory id so at least one browser
    // session stays consistent across turns.
    if (memoryFallback === null) {
      memoryFallback = crypto.randomUUID();
    }
    return memoryFallback;
  }
}
