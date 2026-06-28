"use client"

/**
 * lib/hooks/useEvents.ts
 *
 * Owns the event-list state for the admin console events section.
 * Mirrors the pattern of useDocuments.ts:
 *   - Fetches the event list on mount via listEvents (req events-003)
 *   - Auth error (401/403) from any call → onAuthError() sign-out signal
 *   - create / remove: call matching adminApi fn, fire toasts, refresh (req events-001, events-004)
 *
 * Pure hook — no DOM, no components.  All toasts wired through useToast() from Toaster.tsx.
 *
 * req: events-001, events-003, events-004, events-006
 */

import { useState, useCallback, useEffect, useRef } from "react"
import {
  listEvents,
  createEvent,
  deleteEvent,
  isAdminApiError,
  type EventSummary,
  type EventCreatePayload,
} from "@/lib/adminApi"
import { useToast } from "@/components/admin/Toaster"

// ---------------------------------------------------------------------------
// Public contract
// ---------------------------------------------------------------------------

export interface UseEventsResult {
  /** Current event list. Empty array until the first successful fetch. */
  events: EventSummary[]
  /** Non-null when the last list fetch failed (non-auth error). */
  listError: string | null
  /** True while an explicit refresh (initial load or manual) is in progress. */
  isLoading: boolean
  /** Trigger an explicit list refresh. */
  refresh: () => Promise<void>
  /** Create a new event. On success: success toast + refresh. req events-001. */
  create: (payload: EventCreatePayload) => Promise<boolean>
  /** Delete an event by id. On success: success toast + refresh. req events-004. */
  remove: (id: number) => Promise<void>
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * useEvents(token, onAuthError)
 *
 * @param token       The admin token forwarded as X-Admin-Token on every request.
 * @param onAuthError Called whenever any request returns 401 or 403.
 */
export function useEvents(
  token: string,
  onAuthError: () => void,
): UseEventsResult {
  const [events, setEvents] = useState<EventSummary[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)

  const { addToast } = useToast()

  // Stable ref so closures inside effects always call the latest onAuthError
  const onAuthErrorRef = useRef<() => void>(onAuthError)
  useEffect(() => {
    onAuthErrorRef.current = onAuthError
  }, [onAuthError])

  // ── refresh ───────────────────────────────────────────────────────────────
  const refresh = useCallback(async (): Promise<void> => {
    setIsLoading(true)
    const result = await listEvents(token)
    setIsLoading(false)

    if (isAdminApiError(result)) {
      if (result.kind === "auth") {
        onAuthErrorRef.current()
      } else {
        setListError(result.message)
      }
      return
    }

    setEvents(result)
    setListError(null)
  }, [token])

  // ── initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    const id = setTimeout(() => void refresh(), 0)
    return () => clearTimeout(id)
  }, [refresh])

  // ── create ────────────────────────────────────────────────────────────────
  // POST new event; on success → success toast + refresh.
  // Returns true on success, false on error (so the form can reset).
  // req events-001, events-006
  const create = useCallback(
    async (payload: EventCreatePayload): Promise<boolean> => {
      const result = await createEvent(token, payload)

      if (isAdminApiError(result)) {
        if (result.kind === "auth") {
          onAuthErrorRef.current()
        } else {
          addToast("error", result.message || "Failed to create event — please try again.")
        }
        return false
      }

      addToast("success", `Event "${payload.title}" created.`)
      await refresh()
      return true
    },
    [token, refresh, addToast],
  )

  // ── remove ────────────────────────────────────────────────────────────────
  // DELETE by id; on success → success toast + refresh.
  // req events-004, events-006
  const remove = useCallback(
    async (id: number): Promise<void> => {
      const result = await deleteEvent(token, id)

      if (isAdminApiError(result)) {
        if (result.kind === "auth") {
          onAuthErrorRef.current()
        } else {
          addToast("error", result.message || "Delete failed — please try again.")
        }
        return
      }

      addToast("success", "Event deleted.")
      await refresh()
    },
    [token, refresh, addToast],
  )

  return { events, listError, isLoading, refresh, create, remove }
}
