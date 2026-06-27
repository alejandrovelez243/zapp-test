"use client"

/**
 * lib/hooks/useDocuments.ts
 *
 * Owns the document-list state for the admin console:
 *   - Fetches and refreshes the list via listDocuments (req 002, 013)
 *   - Auth error (401/403) from any call → onAuthError() sign-out signal (req 003)
 *   - Status-poll: polls while any doc is pending/ingesting, stops when all settled (req 012)
 *   - upload / replace / remove: call matching adminApi fn, fire toasts, refresh (req 008-010, 016, 017)
 *
 * Pure hook — no DOM, no components.  All toasts wired through useToast() from Toaster.tsx.
 *
 * req: admin-console-002, admin-console-003, admin-console-008, admin-console-009,
 *      admin-console-010, admin-console-012, admin-console-013, admin-console-016,
 *      admin-console-017
 */

import { useState, useCallback, useEffect, useRef } from "react"
import {
  listDocuments,
  uploadDocument,
  replaceDocument,
  deleteDocument,
  isAdminApiError,
  type DocumentSummary,
} from "@/lib/adminApi"
import { useToast } from "@/components/admin/Toaster"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Polling interval while any document is in-flight (pending | ingesting).
 * Bounded at 2.5 s per spec (2–3 s range).  req 012.
 */
const POLL_INTERVAL_MS = 2_500

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** True when a document status means ingestion is still running. */
function isInFlight(status: string): boolean {
  return status === "pending" || status === "ingesting"
}

/** True when at least one document in the list is in-flight. */
function anyInFlight(docs: DocumentSummary[]): boolean {
  return docs.some((d) => isInFlight(d.status))
}

// ---------------------------------------------------------------------------
// Public contract
// ---------------------------------------------------------------------------

export interface UseDocumentsResult {
  /** Current document list. Empty array until the first successful fetch. */
  docs: DocumentSummary[]
  /** Non-null when the last list fetch failed (non-auth error). */
  listError: string | null
  /**
   * True while an explicit refresh (initial load or manual) is in progress.
   * Polling updates are silent and do NOT flip this flag.
   */
  isLoading: boolean
  /** Trigger an explicit (non-polling) list refresh. req 013. */
  refresh: () => Promise<void>
  /** Upload a new document. On success: success toast + refresh. req 008, 009, 010. */
  upload: (file: File) => Promise<void>
  /** Replace an existing document. On success: success toast + refresh. req 016. */
  replace: (id: number, file: File) => Promise<void>
  /** Delete a document by id. On success: success toast + refresh. req 017. */
  remove: (id: number) => Promise<void>
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * useDocuments(token, onAuthError)
 *
 * @param token       The admin token forwarded as X-Admin-Token on every request.
 *                    Never stored in NEXT_PUBLIC_* — comes from session state. req 002.
 * @param onAuthError Called whenever any request returns 401 or 403; the consumer
 *                    should clear the token and return to the TokenGate. req 003.
 */
export function useDocuments(
  token: string,
  onAuthError: () => void,
): UseDocumentsResult {
  const [docs, setDocs] = useState<DocumentSummary[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)

  const { addToast } = useToast()

  // Stable ref so closures inside effects always call the latest onAuthError
  // without needing it as an effect dependency (avoids stale-closure bugs).
  const onAuthErrorRef = useRef<() => void>(onAuthError)
  useEffect(() => {
    onAuthErrorRef.current = onAuthError
  }, [onAuthError])

  // ── refresh ───────────────────────────────────────────────────────────────
  // Explicit list fetch — sets isLoading so DocumentList can show a spinner.
  // req 002 (sends token via adminApi), 003 (auth → sign-out), 013 (manual refresh).
  const refresh = useCallback(async (): Promise<void> => {
    setIsLoading(true)
    const result = await listDocuments(token)
    setIsLoading(false)

    if (isAdminApiError(result)) {
      if (result.kind === "auth") {
        // 401 / 403: signal the consumer to clear the token. req 003.
        onAuthErrorRef.current()
      } else {
        setListError(result.message)
      }
      return
    }

    setDocs(result)
    setListError(null)
  }, [token])

  // ── initial load ──────────────────────────────────────────────────────────
  // Runs once on mount (and again if the token identity changes, e.g. re-login).
  useEffect(() => {
    void refresh()
  }, [refresh])

  // ── status-poll effect ────────────────────────────────────────────────────
  // While any document is pending/ingesting, poll listDocuments on a bounded
  // interval (2.5 s).  Stop when all are ready/failed or on unmount. req 012.
  //
  // Implementation note: `docs` is listed as a dependency so React re-evaluates
  // whether polling is needed whenever the list changes (via refresh() or a
  // previous poll tick).  The cleanup clears the interval so there is never more
  // than one live interval at a time.
  useEffect(() => {
    if (!anyInFlight(docs)) return        // nothing in-flight → no poll needed

    const intervalId = setInterval(async () => {
      const result = await listDocuments(token)

      if (isAdminApiError(result)) {
        // On auth error during poll, signal sign-out.
        // On any error, stop polling to avoid hammering a failing endpoint.
        clearInterval(intervalId)
        if (result.kind === "auth") {
          onAuthErrorRef.current()
        }
        return
      }

      setDocs(result)

      // Stop the poll once every document has settled. req 012.
      if (!anyInFlight(result)) {
        clearInterval(intervalId)
      }
    }, POLL_INTERVAL_MS)

    return () => clearInterval(intervalId)   // cleanup on unmount or docs change
  }, [docs, token])

  // ── upload ────────────────────────────────────────────────────────────────
  // POST multipart file; on success → success toast + refresh list.
  // req 002 (token), 008 (POST + in-progress feedback via isLoading after refresh),
  // 009 (success toast + refresh), 010 (error toast, list preserved).
  const upload = useCallback(
    async (file: File): Promise<void> => {
      const result = await uploadDocument(token, file)

      if (isAdminApiError(result)) {
        if (result.kind === "auth") {
          onAuthErrorRef.current()
        } else {
          addToast("error", result.message || "Upload failed — please try again.")
        }
        return     // list is intentionally NOT cleared on error. req 010.
      }

      addToast("success", `"${file.name}" uploaded and queued for ingestion.`)
      await refresh()
    },
    [token, refresh, addToast],
  )

  // ── replace ───────────────────────────────────────────────────────────────
  // PUT multipart file to existing document; on success → success toast + refresh.
  // req 002 (token), 016 (PUT + feedback + refresh).
  const replace = useCallback(
    async (id: number, file: File): Promise<void> => {
      const result = await replaceDocument(token, id, file)

      if (isAdminApiError(result)) {
        if (result.kind === "auth") {
          onAuthErrorRef.current()
        } else {
          addToast("error", result.message || "Replace failed — please try again.")
        }
        return
      }

      addToast("success", `"${file.name}" replacement queued for ingestion.`)
      await refresh()
    },
    [token, refresh, addToast],
  )

  // ── remove ────────────────────────────────────────────────────────────────
  // DELETE by id; on success → success toast + refresh.
  // req 002 (token), 017 (DELETE on confirm + toast + remove from list).
  const remove = useCallback(
    async (id: number): Promise<void> => {
      const result = await deleteDocument(token, id)

      if (isAdminApiError(result)) {
        if (result.kind === "auth") {
          onAuthErrorRef.current()
        } else {
          addToast("error", result.message || "Delete failed — please try again.")
        }
        return
      }

      addToast("success", "Document deleted.")
      await refresh()
    },
    [token, refresh, addToast],
  )

  return { docs, listError, isLoading, refresh, upload, replace, remove }
}
