"use client"

/**
 * components/admin/AdminConsole.tsx
 *
 * Client root state machine for the admin console.
 *
 * Two states:
 *   1. No token held → renders <TokenGate> (req admin-console-001).
 *   2. Token held    → renders the console: header with Sign-out, UploadDropzone,
 *                      DocumentList, DeleteConfirm, and <Toaster>.
 *
 * Token lifecycle:
 *   - On mount: restores from sessionStorage (req admin-console-002, 005).
 *   - handleToken: persists to sessionStorage + React state (req admin-console-002).
 *   - handleSignOut: clears sessionStorage + state → back to TokenGate (req admin-console-004).
 *   - onAuthError (from useDocuments): clears token, sets error message,
 *     returns to TokenGate (req admin-console-003).
 *
 * Token safety:
 *   - Token is NEVER read from NEXT_PUBLIC_* or any build-time variable.
 *   - Token lives only in sessionStorage + React state (req admin-console-005).
 *
 * req: admin-console-001, admin-console-002, admin-console-003,
 *      admin-console-004, admin-console-005
 */

import * as React from "react"
import Link from "next/link"
import { TokenGate } from "@/components/admin/TokenGate"
import { UploadDropzone } from "@/components/admin/UploadDropzone"
import { DocumentList } from "@/components/admin/DocumentList"
import { DeleteConfirm } from "@/components/admin/DeleteConfirm"
import { Toaster } from "@/components/admin/Toaster"
import { useDocuments } from "@/lib/hooks/useDocuments"
import type { DocumentSummary } from "@/lib/adminApi"

// ── SessionStorage key ────────────────────────────────────────────────────────
// A plain literal, never a NEXT_PUBLIC_* env var (req admin-console-005).
const SESSION_KEY = "admin_token"

// ── AdminConsole ──────────────────────────────────────────────────────────────

/**
 * AdminConsole is the single client island that owns the auth/gate state
 * machine and mounts all admin-console sub-components.
 *
 * It is not a pure presentational component — it orchestrates:
 *   - Token gate vs. console view (req 001)
 *   - Token persistence in sessionStorage (req 002, 005)
 *   - Auth-error → re-gate path (req 003)
 *   - Sign-out control (req 004)
 *   - DeleteConfirm open/close/confirm/cancel state (req 017, 018)
 *   - busy tracking for in-flight actions (upload + replace/delete)
 *   - Single <Toaster /> mount (req 020)
 */
export function AdminConsole() {
  // ── Token state ─────────────────────────────────────────────────────────────
  // Initialised lazily from sessionStorage so it is only read once in the
  // browser — never during SSR (typeof window guard not required with lazy
  // initialiser, but we guard the sessionStorage call to be safe).
  const [token, setToken] = React.useState<string>(() => {
    if (typeof window === "undefined") return ""
    return sessionStorage.getItem(SESSION_KEY) ?? ""
  })

  // ── Auth error message ───────────────────────────────────────────────────────
  // Set by onAuthError; shown in <TokenGate error={authError}> when the gate
  // is re-displayed after a 401/403 (req admin-console-003).
  const [authError, setAuthError] = React.useState<string | null>(null)

  // ── Token handlers ───────────────────────────────────────────────────────────

  /**
   * handleToken — called by <TokenGate> when the admin submits a token.
   * Persists to sessionStorage + React state; clears any prior auth error.
   * req admin-console-002, admin-console-005
   */
  function handleToken(submittedToken: string) {
    sessionStorage.setItem(SESSION_KEY, submittedToken)
    setToken(submittedToken)
    setAuthError(null)
  }

  /**
   * handleSignOut — clears the stored token and returns to the gate.
   * req admin-console-004
   */
  function handleSignOut() {
    sessionStorage.removeItem(SESSION_KEY)
    setToken("")
    setAuthError(null)
  }

  /**
   * onAuthError — called by useDocuments whenever any request returns 401/403.
   * Clears the token and sets an error message so the gate shows feedback.
   * req admin-console-003
   */
  const onAuthError = React.useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    setToken("")
    setAuthError("Your admin token is missing or has expired. Please enter it again.")
  }, [])

  // ── Document hook ────────────────────────────────────────────────────────────
  // Only called when a token is held — when no token is set the TokenGate is
  // rendered instead and the hook call receives an empty string, but since the
  // DocumentsConsole branch is not rendered the hook is effectively dormant.
  // We call the hook unconditionally (rules of hooks) with the current token.
  // req admin-console-002 (token forwarded via hook), admin-console-003 (auth signal).
  const { docs, listError, isLoading, refresh, upload, replace, remove } =
    useDocuments(token, onAuthError)

  // ── Busy tracking ────────────────────────────────────────────────────────────
  // UploadDropzone shows a "busy" state while an upload is in flight.
  const [uploadBusy, setUploadBusy] = React.useState(false)
  // busyId: id of the document currently being replaced or deleted.
  const [busyId, setBusyId] = React.useState<number | null>(null)

  // ── DeleteConfirm state ──────────────────────────────────────────────────────
  // AdminConsole owns the dialog open/close + the target document so that
  // DocumentList can simply call onDelete(doc) to trigger it.
  const [deleteTarget, setDeleteTarget] = React.useState<DocumentSummary | null>(null)
  const [deleteBusy, setDeleteBusy] = React.useState(false)

  // ── Wrapped action handlers ──────────────────────────────────────────────────

  /**
   * handleUpload — wraps useDocuments.upload with uploadBusy tracking.
   * req admin-console-008 (in-progress feedback in UploadDropzone)
   */
  async function handleUpload(file: File) {
    setUploadBusy(true)
    try {
      await upload(file)
    } finally {
      setUploadBusy(false)
    }
  }

  /**
   * handleReplace — wraps useDocuments.replace with busyId tracking.
   * req admin-console-016
   */
  async function handleReplace(id: number, file: File) {
    setBusyId(id)
    try {
      await replace(id, file)
    } finally {
      setBusyId(null)
    }
  }

  /**
   * handleDeleteRequest — opens DeleteConfirm for the given document.
   * DocumentList calls this when the admin clicks Delete.
   * req admin-console-017
   */
  function handleDeleteRequest(doc: DocumentSummary) {
    setDeleteTarget(doc)
  }

  /**
   * handleDeleteConfirm — the admin confirmed deletion; issue the DELETE.
   * req admin-console-017
   */
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

  /**
   * handleDeleteCancel — the admin cancelled; close the dialog, send nothing.
   * req admin-console-018
   */
  function handleDeleteCancel() {
    setDeleteTarget(null)
    setDeleteBusy(false)
  }

  // ── Gate / console split ─────────────────────────────────────────────────────

  // No token → show the gate. All document endpoints are NOT called in this
  // branch (hook is initialised with an empty token but the RSC page still
  // defers to this client island for all management UI). req 001, 005.
  if (!token) {
    return (
      <>
        {/* Toaster is always mounted so aria-live region is registered early. */}
        <Toaster />
        <TokenGate onSubmit={handleToken} error={authError} />
      </>
    )
  }

  // ── Console ─────────────────────────────────────────────────────────────────

  return (
    <>
      {/* Single Toaster mount — aria-live="polite" region. req admin-console-020. */}
      <Toaster />

      {/* Sign-out control — top-right of the page column (req admin-console-004). */}
      <div className="flex justify-end mb-4">
        <button
          type="button"
          onClick={handleSignOut}
          className={[
            // Ghost style — unobtrusive, editorial
            "inline-flex items-center gap-1.5 rounded px-3 py-1.5",
            "text-xs font-medium font-sans text-muted-foreground",
            "border border-border",
            "transition-colors duration-150 hover:text-foreground hover:bg-muted/50",
            // Focus ring (req admin-console-019)
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            "motion-reduce:transition-none",
          ].join(" ")}
        >
          {/* Lock icon — inline SVG, no extra dep */}
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

      {/* Upload dropzone (req 006, 007, 008) — fed by handleUpload wrapper. */}
      <UploadDropzone onFile={handleUpload} busy={uploadBusy} />

      {/* Vertical rhythm */}
      <div className="mt-8" />

      {/* Document list (req 011, 013, 014, 020). */}
      <DocumentList
        docs={docs}
        isLoading={isLoading}
        listError={listError}
        onRefresh={refresh}
        onReplace={handleReplace}
        onDelete={handleDeleteRequest}
        busyId={busyId}
      />

      {/* Delete confirmation dialog — owned here; never renders until deleteTarget is set. */}
      {/* req admin-console-017, admin-console-018 */}
      <DeleteConfirm
        open={deleteTarget !== null}
        doc={deleteTarget}
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
        busy={deleteBusy}
      />
    </>
  )
}

export default AdminConsole
