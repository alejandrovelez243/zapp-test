"use client"

/**
 * components/admin/DocumentList.tsx
 *
 * Presentational list of documents in the admin console.
 *
 * Responsibilities:
 *   - Header: "Documents" serif heading + a manual Refresh button (req 013).
 *   - Loading state: muted inline indicator while isLoading is true.
 *   - Error state: role="alert" block for listError (non-auth, non-fatal errors).
 *   - Empty state: calm typographic invitation to upload the first document
 *     when docs is empty, not loading, and no error (req 014).
 *   - Document list: one <DocumentCard> per doc; onReplace/onDelete wired to
 *     bubble up to the parent (req 011). onDelete passes the full doc so
 *     AdminConsole/DeleteConfirm can confirm before deleting (task 7/9).
 *   - Aria-live region: a visually-hidden role="status" announces loading
 *     completion and list change events to assistive technology (req 020).
 *
 * This component is intentionally presentational — it never calls useDocuments
 * directly. Props are passed in by AdminConsole (task 9) from the hook's return
 * value. This makes the component deterministically testable with any doc state.
 *
 * req: admin-console-011, admin-console-013, admin-console-014, admin-console-020
 */

import * as React from "react"
import { cn } from "@/lib/utils"
import { DocumentCard } from "@/components/admin/DocumentCard"
import type { DocumentSummary } from "@/lib/adminApi"

// ── Refresh icon (inline SVG, no external dep) ────────────────────────────────

function RefreshIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path
        d="M13.5 2.5A6.5 6.5 0 0 0 2.5 8M2.5 13.5A6.5 6.5 0 0 0 13.5 8"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <path
        d="M13.5 2.5v3h-3M2.5 13.5v-3h3"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface DocumentListProps {
  /** The current document list from useDocuments. */
  docs: DocumentSummary[]
  /**
   * True while an explicit refresh (initial load or manual) is in progress.
   * Polling ticks do not flip this. Disables the Refresh button during load.
   */
  isLoading: boolean
  /**
   * Non-null when the last list fetch failed (non-auth error).
   * Displayed inline via role="alert".
   */
  listError: string | null
  /**
   * Trigger an explicit (non-polling) list refresh.
   * req: admin-console-013 — manual refresh control.
   */
  onRefresh(): void
  /**
   * Called with (docId, file) when the admin picks a replacement file via
   * DocumentCard. Parent (AdminConsole) delegates to useDocuments.replace().
   * req: admin-console-016
   */
  onReplace(id: number, file: File): void
  /**
   * Called with the full DocumentSummary when the admin clicks Delete.
   * The parent (AdminConsole, task 9) opens DeleteConfirm before issuing the
   * DELETE request. This component only bubbles the event.
   * req: admin-console-017 / admin-console-018 (confirm is the parent's concern)
   */
  onDelete(doc: DocumentSummary): void
  /**
   * Id of the document currently having an action applied (upload/replace/delete
   * in flight). When set, the matching DocumentCard disables its actions.
   */
  busyId?: number | null
}

// ── DocumentList ──────────────────────────────────────────────────────────────

/**
 * DocumentList renders the document corpus table for the admin console.
 *
 * Layout (top → bottom):
 *   [header: "Documents" heading · Refresh button]
 *   [error alert  — only when listError is set]
 *   [loading line — only while isLoading is true]
 *   [empty state  — only when docs is empty, not loading, no error]
 *   [document cards — one per doc in docs]
 *   [sr-only aria-live region — status announcements]
 *
 * req: admin-console-011, admin-console-013, admin-console-014, admin-console-020
 */
export function DocumentList({
  docs,
  isLoading,
  listError,
  onRefresh,
  onReplace,
  onDelete,
  busyId = null,
}: DocumentListProps) {
  // ── Derived state ───────────────────────────────────────────────────────────

  /** True when there is nothing to show and the list is idle with no error. */
  const isEmpty = !isLoading && !listError && docs.length === 0

  // ── Aria-live announcement (req 020) ────────────────────────────────────────
  //
  // A separate sr-only live region announces loading transitions to screen
  // readers. We track the previous loading state with a ref so we can detect
  // when isLoading transitions from true → false and compose the right sentence.
  //
  // We do NOT use the Toaster for these list-state changes — they are not user-
  // triggered outcomes (success/error) but ambient status — so a dedicated quiet
  // region avoids spamming the toast queue.

  const [announcement, setAnnouncement] = React.useState<string>("")
  const prevLoadingRef = React.useRef<boolean>(isLoading)
  const prevDocCountRef = React.useRef<number>(docs.length)

  React.useEffect(() => {
    const wasLoading = prevLoadingRef.current
    const prevCount = prevDocCountRef.current
    prevLoadingRef.current = isLoading
    prevDocCountRef.current = docs.length

    if (wasLoading && !isLoading) {
      // A load (initial or manual refresh) just completed.
      if (listError) {
        setAnnouncement("Failed to load documents. See the error message.")
      } else if (docs.length === 0) {
        setAnnouncement("Document list loaded. No documents yet.")
      } else {
        const n = docs.length
        setAnnouncement(
          `Document list refreshed. ${n} document${n === 1 ? "" : "s"}.`
        )
      }
    } else if (!isLoading && docs.length !== prevCount) {
      // List changed without a loading cycle (unlikely with current hook but
      // defensive — e.g. an optimistic update path in the future).
      const n = docs.length
      if (n > 0) {
        setAnnouncement(
          `Document list updated. ${n} document${n === 1 ? "" : "s"}.`
        )
      }
    }
  }, [isLoading, listError, docs.length])

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <section
      aria-label="Document list"
      className="flex flex-col gap-4"
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      {/*
       * req 013: the Refresh button is a first-class control alongside the heading.
       * Disabled while a load is already in progress to prevent concurrent fetches.
       * The visible icon + text label satisfies WCAG 1.4.1 (not color alone).
       */}
      <div className="flex items-baseline justify-between gap-3">
        <h2
          className={cn(
            "font-serif text-xl font-normal leading-tight tracking-tight",
            "text-foreground"
          )}
        >
          Documents
        </h2>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          aria-label="Refresh document list"
          aria-busy={isLoading}
          className={cn(
            // Ghost style — matches the design system's action tone
            "inline-flex items-center gap-1.5 rounded px-2.5 py-1",
            "text-xs font-medium font-sans text-muted-foreground",
            "border border-transparent",
            // Hover: subtle tint
            "transition-colors duration-150 hover:text-foreground hover:bg-muted/50",
            // Focus ring using the aubergine --ring token (req 019)
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            // Disabled — during loading cycle
            isLoading && "pointer-events-none opacity-40 cursor-not-allowed",
            // Reduced motion: transition suppressed globally via globals.css
            "motion-reduce:transition-none"
          )}
        >
          <RefreshIcon
            className={cn(
              "size-3.5 shrink-0",
              // Gentle spin while loading
              isLoading && "animate-spin motion-reduce:animate-none"
            )}
          />
          {isLoading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Hairline rule under the header — editorial rhythm */}
      <hr className="border-t border-border" aria-hidden="true" />

      {/* ── Error alert ────────────────────────────────────────────────────── */}
      {/*
       * role="alert" causes assistive technology to announce the error
       * immediately (assertive), appropriate for an unexpected failure.
       * Note: auth errors are handled by AdminConsole (sign-out signal);
       * listError only carries non-auth errors from useDocuments. req 020.
       */}
      {listError && (
        <p
          role="alert"
          className={cn(
            "rounded-sm border border-destructive/20 bg-destructive/5",
            "px-3 py-2 text-sm font-sans text-foreground/80 leading-snug"
          )}
        >
          {listError}
        </p>
      )}

      {/* ── Loading indicator ───────────────────────────────────────────────── */}
      {/*
       * A quiet textual loading hint. Kept visually subtle — the Refresh button
       * already shows a spinning icon + "Refreshing…" label, so this line only
       * renders when the list area itself is blank (initial load).
       * Not aria-live here — the sr-only region below handles announcements.
       */}
      {isLoading && docs.length === 0 && (
        <p
          aria-hidden="true"
          className={cn(
            "py-8 text-center text-sm font-sans text-muted-foreground/70",
            "select-none"
          )}
        >
          Loading…
        </p>
      )}

      {/* ── Empty state (req 014) ───────────────────────────────────────────── */}
      {/*
       * Only shown when docs is empty, not loading, and no error.
       * Editorial prose inviting the first upload — no icon, no button here;
       * the UploadDropzone (task 4) above this section is the action surface.
       */}
      {isEmpty && (
        <div
          className={cn(
            "flex flex-col items-center gap-3",
            "py-12 px-6 text-center"
          )}
          aria-label="No documents yet"
        >
          {/* Decorative hairline meander — visual nod to the .rule-meander design token */}
          <span
            aria-hidden="true"
            className="block w-8 border-t border-border"
          />

          <p
            className={cn(
              "font-serif text-lg font-normal text-foreground/70",
              "leading-snug"
            )}
          >
            No documents yet.
          </p>

          <p
            className={cn(
              "max-w-[48ch] text-sm font-sans text-muted-foreground leading-relaxed"
            )}
          >
            Upload a PDF, Markdown, or plain-text file above to seed the FAQ
            corpus. Once ingested, the document will appear here with its status.
          </p>
        </div>
      )}

      {/* ── Document cards (req 011) ────────────────────────────────────────── */}
      {/*
       * Rendered as a <ul> list so screen readers announce item count and can
       * navigate by item. Each <li> wraps a <DocumentCard>.
       *
       * onReplace binds the doc id so DocumentCard only needs to hand back the
       * File object (matching its prop signature).
       * onDelete bubbles the full DocumentSummary up to AdminConsole which
       * opens <DeleteConfirm> (task 7) before the DELETE is sent. req 017/018.
       *
       * busyId: only the card whose id matches has its actions disabled, so
       * other documents stay actionable during a concurrent operation.
       */}
      {!isLoading && docs.length > 0 && (
        <ul
          aria-label={`${docs.length} document${docs.length === 1 ? "" : "s"}`}
          className="flex flex-col gap-2"
        >
          {docs.map((doc) => (
            <li
              key={doc.id}
              className={cn(
                // Calm fade-in when a card enters (upload success / list refresh).
                // tw-animate-css animate-in + fade-in produces a CSS keyframe on mount.
                // Exit animations require a library; enter-only is the pragmatic choice.
                // Gated by motion-reduce utility + global animation-duration override.
                // req: admin-console-021 (classical design system — calm motion)
                "animate-in fade-in duration-200 motion-reduce:animate-none"
              )}
            >
              <DocumentCard
                doc={doc}
                onReplace={(file: File) => onReplace(doc.id, file)}
                onDelete={() => onDelete(doc)}
                busy={busyId === doc.id}
              />
            </li>
          ))}
        </ul>
      )}

      {/* ── Aria-live status region (req 020) ───────────────────────────────── */}
      {/*
       * This region is visually hidden (sr-only) — its sole purpose is to
       * announce list-state transitions (load complete, count changed) to
       * screen readers via aria-live="polite". "polite" means the announcement
       * waits until the reader finishes current speech before inserting the
       * status, which is appropriate for these background updates.
       *
       * aria-atomic="true" forces the full sentence to be re-read on each
       * change rather than diffing partial text. The announcement string is set
       * by the useEffect above when isLoading flips from true → false.
       *
       * This region is separate from the Toaster (aria-live="polite" role="log")
       * so user-triggered toast events and background status updates do not
       * interleave in the same log stream.
       */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {announcement}
      </div>
    </section>
  )
}

export default DocumentList
