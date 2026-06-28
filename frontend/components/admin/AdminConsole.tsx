"use client"

/**
 * components/admin/AdminConsole.tsx
 *
 * Client root state machine for the admin console.
 *
 * Two top-level states:
 *   1. No token held → renders <TokenGate> (req admin-console-001).
 *   2. Token held    → renders the console: tab switcher + section content.
 *
 * Console sections (tabbed):
 *   - Documents: UploadDropzone + DocumentList (existing; req faq-rag-001..008)
 *   - Events: EventForm + EventList (new; req events-001..006)
 *
 * Token lifecycle:
 *   - On mount: restores from sessionStorage (req admin-console-002, 005).
 *   - handleToken: persists to sessionStorage + React state (req admin-console-002).
 *   - handleSignOut: clears sessionStorage + state → back to TokenGate (req admin-console-004).
 *   - onAuthError (from useDocuments / useEvents): clears token, sets error message,
 *     returns to TokenGate (req admin-console-003).
 *
 * Token safety:
 *   - Token is NEVER read from NEXT_PUBLIC_* or any build-time variable.
 *   - Token lives only in sessionStorage + React state (req admin-console-005).
 *
 * req: admin-console-001 … admin-console-005, events-001, events-003..006
 */

import * as React from "react"
import { cn } from "@/lib/utils"
import { TokenGate } from "@/components/admin/TokenGate"
import { UploadDropzone } from "@/components/admin/UploadDropzone"
import { DocumentList } from "@/components/admin/DocumentList"
import { DeleteConfirm } from "@/components/admin/DeleteConfirm"
import { Toaster } from "@/components/admin/Toaster"
import { EventForm } from "@/components/admin/EventForm"
import { EventList } from "@/components/admin/EventList"
import { useDocuments } from "@/lib/hooks/useDocuments"
import { useEvents } from "@/lib/hooks/useEvents"
import { listEnrollments, isAdminApiError } from "@/lib/adminApi"
import type { DocumentSummary, EventSummary, Enrollment } from "@/lib/adminApi"

// ── SessionStorage key ────────────────────────────────────────────────────────
const SESSION_KEY = "admin_token"

// ── Section type ──────────────────────────────────────────────────────────────
type ConsoleSection = "documents" | "events"

// ── AdminConsole ──────────────────────────────────────────────────────────────

/**
 * AdminConsole is the single client island that owns the auth/gate state
 * machine and mounts all admin-console sub-components.
 *
 * It orchestrates:
 *   - Token gate vs. console view (req 001)
 *   - Token persistence in sessionStorage (req 002, 005)
 *   - Auth-error → re-gate path (req 003)
 *   - Sign-out control (req 004)
 *   - Documents section: DeleteConfirm open/close/confirm/cancel (req 017, 018)
 *   - Events section: EventForm + EventList + event DeleteConfirm
 *   - Single <Toaster /> mount (req 020)
 */
export function AdminConsole() {
  // ── Token state ─────────────────────────────────────────────────────────────
  const [token, setToken] = React.useState<string>(() => {
    if (typeof window === "undefined") return ""
    return sessionStorage.getItem(SESSION_KEY) ?? ""
  })

  // ── Auth error message ───────────────────────────────────────────────────────
  const [authError, setAuthError] = React.useState<string | null>(null)

  // ── Active console section ───────────────────────────────────────────────────
  const [section, setSection] = React.useState<ConsoleSection>("documents")

  // ── Token handlers ───────────────────────────────────────────────────────────

  function handleToken(submittedToken: string) {
    sessionStorage.setItem(SESSION_KEY, submittedToken)
    setToken(submittedToken)
    setAuthError(null)
  }

  function handleSignOut() {
    sessionStorage.removeItem(SESSION_KEY)
    setToken("")
    setAuthError(null)
  }

  const onAuthError = React.useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    setToken("")
    setAuthError("Your admin token is missing or has expired. Please enter it again.")
  }, [])

  // ── Document hook ────────────────────────────────────────────────────────────
  const { docs, listError, isLoading, refresh, upload, replace, remove } =
    useDocuments(token, onAuthError)

  // ── Events hook ──────────────────────────────────────────────────────────────
  const {
    events,
    listError: eventsListError,
    isLoading: eventsLoading,
    refresh: refreshEvents,
    create: createEvent,
    remove: removeEvent,
  } = useEvents(token, onAuthError)

  // ── Busy tracking — documents ─────────────────────────────────────────────────
  const [uploadBusy, setUploadBusy] = React.useState(false)
  const [busyId, setBusyId] = React.useState<number | null>(null)

  // ── DeleteConfirm state — documents ──────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = React.useState<DocumentSummary | null>(null)
  const [deleteBusy, setDeleteBusy] = React.useState(false)

  // ── Busy tracking — events ────────────────────────────────────────────────────
  const [eventBusyId, setEventBusyId] = React.useState<number | null>(null)

  // ── DeleteConfirm state — events ─────────────────────────────────────────────
  const [deleteEventTarget, setDeleteEventTarget] = React.useState<EventSummary | null>(null)
  const [deleteEventBusy, setDeleteEventBusy] = React.useState(false)

  // ── Document action handlers ─────────────────────────────────────────────────

  async function handleUpload(file: File) {
    setUploadBusy(true)
    try {
      await upload(file)
    } finally {
      setUploadBusy(false)
    }
  }

  async function handleReplace(id: number, file: File) {
    setBusyId(id)
    try {
      await replace(id, file)
    } finally {
      setBusyId(null)
    }
  }

  function handleDeleteRequest(doc: DocumentSummary) {
    setDeleteTarget(doc)
  }

  async function handleDeleteConfirm() {
    if (!deleteTarget) return
    setDeleteBusy(true)
    setBusyId(deleteTarget.id)
    try {
      await remove(deleteTarget.id)
    } finally {
      setDeleteBusy(false)
      setBusyId(null)
      setDeleteTarget(null)
    }
  }

  function handleDeleteCancel() {
    setDeleteTarget(null)
    setDeleteBusy(false)
  }

  // ── Event action handlers ────────────────────────────────────────────────────

  function handleEventDeleteRequest(event: EventSummary) {
    setDeleteEventTarget(event)
  }

  async function handleEventDeleteConfirm() {
    if (!deleteEventTarget) return
    setDeleteEventBusy(true)
    setEventBusyId(deleteEventTarget.id)
    try {
      await removeEvent(deleteEventTarget.id)
    } finally {
      setDeleteEventBusy(false)
      setEventBusyId(null)
      setDeleteEventTarget(null)
    }
  }

  function handleEventDeleteCancel() {
    setDeleteEventTarget(null)
    setDeleteEventBusy(false)
  }

  /**
   * fetchEnrollments — bound to the current admin token so EventList rows
   * can fetch registrant data without knowing the token themselves.
   * Surfacing auth errors back to onAuthError; non-auth errors return empty.
   * req: events-005, events-006
   */
  const fetchEnrollments = React.useCallback(
    async (id: number): Promise<Enrollment[]> => {
      const result = await listEnrollments(token, id)
      if (isAdminApiError(result)) {
        if (result.kind === "auth") onAuthError()
        return []
      }
      return result
    },
    [token, onAuthError]
  )

  // ── Gate ─────────────────────────────────────────────────────────────────────

  if (!token) {
    return (
      <>
        <Toaster />
        <TokenGate onSubmit={handleToken} error={authError} />
      </>
    )
  }

  // ── Console ──────────────────────────────────────────────────────────────────

  return (
    <>
      {/* Single Toaster mount — aria-live="polite" region. req admin-console-020. */}
      <Toaster />

      {/* Sign-out control */}
      <div className="flex justify-end mb-4">
        <button
          type="button"
          onClick={handleSignOut}
          className={[
            "inline-flex items-center gap-1.5 rounded px-3 py-1.5",
            "text-xs font-medium font-sans text-muted-foreground",
            "border border-border",
            "transition-colors duration-150 hover:text-foreground hover:bg-muted/50",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            "motion-reduce:transition-none",
          ].join(" ")}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            aria-hidden="true"
            focusable="false"
          >
            <rect
              x="2"
              y="5.5"
              width="8"
              height="5.5"
              rx="1"
              stroke="currentColor"
              strokeWidth="1.2"
            />
            <path
              d="M4 5.5V3.5a2 2 0 1 1 4 0v2"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
            />
          </svg>
          Sign out
        </button>
      </div>

      {/* ── Tab bar ──────────────────────────────────────────────────────────── */}
      {/*
       * Simple editorial tab switcher — text tabs with an underline indicator.
       * Uses role="tablist" / role="tab" / aria-selected for accessibility.
       * Tab panels are rendered conditionally below.
       */}
      <div
        role="tablist"
        aria-label="Admin sections"
        className="flex gap-0 border-b border-border mb-8"
      >
        <button
          role="tab"
          id="tab-documents"
          aria-selected={section === "documents"}
          aria-controls="tabpanel-documents"
          onClick={() => setSection("documents")}
          className={cn(
            "px-4 pb-2 pt-1 text-sm font-sans border-b-2 -mb-px",
            "transition-colors duration-150 motion-reduce:transition-none",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 rounded-t",
            section === "documents"
              ? "border-primary text-foreground font-medium"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          Documents
        </button>

        <button
          role="tab"
          id="tab-events"
          aria-selected={section === "events"}
          aria-controls="tabpanel-events"
          onClick={() => setSection("events")}
          className={cn(
            "px-4 pb-2 pt-1 text-sm font-sans border-b-2 -mb-px",
            "transition-colors duration-150 motion-reduce:transition-none",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 rounded-t",
            section === "events"
              ? "border-primary text-foreground font-medium"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          Events
        </button>
      </div>

      {/* ── Documents tab panel ──────────────────────────────────────────────── */}
      <div
        id="tabpanel-documents"
        role="tabpanel"
        aria-labelledby="tab-documents"
        hidden={section !== "documents"}
      >
        {/* Upload dropzone */}
        <UploadDropzone onFile={handleUpload} busy={uploadBusy} />

        <div className="mt-8" />

        {/* Document list */}
        <DocumentList
          docs={docs}
          isLoading={isLoading}
          listError={listError}
          onRefresh={refresh}
          onReplace={handleReplace}
          onDelete={handleDeleteRequest}
          busyId={busyId}
        />

        {/* Document delete confirmation */}
        <DeleteConfirm
          open={deleteTarget !== null}
          doc={deleteTarget}
          onConfirm={handleDeleteConfirm}
          onCancel={handleDeleteCancel}
          busy={deleteBusy}
        />
      </div>

      {/* ── Events tab panel ──────────────────────────────────────────────────── */}
      <div
        id="tabpanel-events"
        role="tabpanel"
        aria-labelledby="tab-events"
        hidden={section !== "events"}
      >
        {/* Create-event form */}
        <div className="mb-8">
          <h2
            className={cn(
              "font-serif text-xl font-normal leading-tight tracking-tight text-foreground mb-4"
            )}
          >
            Create event
          </h2>
          <hr className="border-t border-border mb-5" aria-hidden="true" />
          <EventForm onSubmit={createEvent} />
        </div>

        <div className="mt-8" />

        {/* Events list with registrants */}
        <EventList
          events={events}
          isLoading={eventsLoading}
          listError={eventsListError}
          onRefresh={refreshEvents}
          onDelete={handleEventDeleteRequest}
          busyId={eventBusyId}
          fetchEnrollments={fetchEnrollments}
        />

        {/* Event delete confirmation — reuses DeleteConfirm with { name: event.title } */}
        <DeleteConfirm
          open={deleteEventTarget !== null}
          doc={deleteEventTarget ? { name: deleteEventTarget.title } : null}
          onConfirm={handleEventDeleteConfirm}
          onCancel={handleEventDeleteCancel}
          busy={deleteEventBusy}
        />
      </div>
    </>
  )
}

export default AdminConsole
