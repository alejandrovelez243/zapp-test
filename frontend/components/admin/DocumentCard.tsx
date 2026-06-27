"use client"

/**
 * components/admin/DocumentCard.tsx
 *
 * One document row in the admin console: filename (mono) + <StatusPill> +
 * Replace and Delete action buttons.
 *
 * Design: a token-styled row — hairline border, paper background, no heavy
 * card shadow. Filename uses the project's mono face (JetBrains Mono via
 * globals.css `font-mono`). Actions use the aubergine accent for focus rings
 * (`--ring` via the established token system).
 *
 * Replace flow (req admin-console-016):
 *   A hidden <input type="file"> is opened programmatically when the user
 *   clicks "Replace" or activates it by keyboard (Enter/Space delegated via
 *   the button). The file is validated against the same extension whitelist
 *   used by UploadDropzone (.pdf / .md / .txt); invalid files are rejected
 *   inline with a role="alert" message before onReplace is ever called.
 *
 * Delete flow (req admin-console-017):
 *   Calling onDelete() hands control to the parent (DocumentList / AdminConsole
 *   via task 7 DeleteConfirm). This component does NOT open a confirm dialog;
 *   it only invokes the callback. This keeps the confirmation modal as a
 *   sibling concern (see design.md component contracts).
 *
 * Keyboard operability (req admin-console-019):
 *   Both buttons are standard <button> elements — fully keyboard reachable.
 *   focus-visible:ring-2 with the accent ring color provides the visible
 *   focus indicator. busy=true disables both actions (aria-disabled + disabled).
 *
 * req: admin-console-011, admin-console-016, admin-console-019
 */

import * as React from "react"
import { cn } from "@/lib/utils"
import { StatusPill } from "@/components/admin/StatusPill"
import type { DocumentSummary } from "@/lib/adminApi"
import { validateFile } from "@/lib/validateFile"

// ── Props ─────────────────────────────────────────────────────────────────────

export interface DocumentCardProps {
  /** The document to display. */
  doc: DocumentSummary
  /**
   * Called with a validated File when the admin selects a replacement.
   * NOT called if the file extension is invalid.
   * (req admin-console-016)
   */
  onReplace: (file: File) => void
  /**
   * Called when the admin clicks Delete. The parent is responsible for
   * showing a confirmation dialog before sending the DELETE request.
   * (req admin-console-017/018 — confirm lives in DeleteConfirm, task 7)
   */
  onDelete: () => void
  /**
   * When true, both Replace and Delete are disabled (e.g. an action is in
   * flight). Conveys disabled state via both the HTML `disabled` attribute
   * and `aria-disabled` for redundancy.
   */
  busy?: boolean
}

// ── DocumentCard ──────────────────────────────────────────────────────────────

/**
 * DocumentCard renders one document as a horizontal token-styled row.
 *
 * Layout (left → right):
 *   [filename in mono]  [StatusPill]  [spacer]  [Replace]  [Delete]
 *
 * The row uses a hairline border (`border-border`), paper background
 * (`bg-background`), and the project's standard spacing tokens.
 *
 * req: admin-console-011 — filename + status pill per document
 * req: admin-console-016 — Replace action with file-picker + ext validation
 * req: admin-console-019 — keyboard operable; visible --ring focus indicator
 */
export function DocumentCard({
  doc,
  onReplace,
  onDelete,
  busy = false,
}: DocumentCardProps) {
  // Hidden file input ref — opened programmatically by the Replace button.
  const fileInputRef = React.useRef<HTMLInputElement>(null)

  // Inline error for Replace file-type validation (req admin-console-007 /016).
  const [replaceError, setReplaceError] = React.useState<string | null>(null)

  // Unique id for the error message so it can be associated with the button.
  const errorId = React.useId()

  // ── Handlers ───────────────────────────────────────────────────────────────

  /** Open the hidden file picker when Replace is activated. */
  function handleReplaceClick() {
    if (busy) return
    // Clear any prior error so the user sees a fresh attempt.
    setReplaceError(null)
    fileInputRef.current?.click()
  }

  /**
   * Process the file chosen in the hidden picker.
   * Validate extension first; only call onReplace on a valid file.
   */
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    // Reset the input value so choosing the same file again still fires onChange.
    e.target.value = ""

    if (!file) return

    const error = validateFile(file)
    if (error) {
      setReplaceError(error)
      return
    }

    setReplaceError(null)
    onReplace(file)
  }

  // ── Shared button styles ────────────────────────────────────────────────────

  /**
   * Base classes for the action buttons.
   * - No background fill (ghost-style, text only).
   * - Visible focus ring using the established --ring / accent token.
   * - Disabled state via Tailwind opacity + pointer-events-none.
   * (req admin-console-019)
   */
  const actionButton = cn(
    // Layout
    "inline-flex items-center justify-center",
    "rounded px-2.5 py-1",
    // Typography — small label, Public Sans (sans by default)
    "text-xs font-medium leading-none",
    // Transition — calm, reduced-motion respected via globals.css
    "transition-colors duration-150 motion-reduce:transition-none",
    // Focus ring — accent aubergine, meets WCAG AA visibility
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
    // Disabled state
    busy && "pointer-events-none opacity-40 cursor-not-allowed"
  )

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <article
      /**
       * role="article" is implicit for <article>. The name is provided by the
       * h3-equivalent filename inside, satisfying accessible name requirements.
       */
      aria-label={`Document: ${doc.name}`}
      className={cn(
        // Token-styled row — hairline border, paper bg, comfortable padding
        "flex flex-col gap-1.5",
        "rounded-sm border border-border bg-background",
        "px-4 py-3",
        // Calm hover tint — paper surface lifts slightly toward muted
        "transition-colors duration-150 motion-reduce:transition-none hover:bg-muted/40"
      )}
    >
      {/* ── Primary row: name · pill · actions ──────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">

        {/* Filename — mono face per design.md; truncated with title for full name */}
        <span
          className={cn(
            "font-mono text-sm text-foreground",
            "min-w-0 flex-1 truncate",
            // Accessible: title reveals the full name on hover/focus
          )}
          title={doc.name}
        >
          {doc.name}
        </span>

        {/* Status pill (req admin-console-011) */}
        <StatusPill status={doc.status} />

        {/* Actions — pushed to the right */}
        <div className="flex items-center gap-1.5 shrink-0" role="group" aria-label="Document actions">

          {/* Replace button (req admin-console-016) */}
          <button
            type="button"
            onClick={handleReplaceClick}
            disabled={busy}
            aria-disabled={busy}
            aria-describedby={replaceError ? errorId : undefined}
            className={cn(
              actionButton,
              // Neutral ghost — aubergine on hover, calm by default
              "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            Replace
          </button>

          {/* Visual separator hairline */}
          <span aria-hidden="true" className="h-3.5 w-px bg-border" />

          {/* Delete button — calls onDelete(); confirm is parent's concern */}
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            aria-disabled={busy}
            className={cn(
              actionButton,
              // Calm destructive tint — full opacity for WCAG AA contrast (req admin-console-021)
              // text-destructive/70 ≈ 3.45:1 on paper (FAILS AA); full opacity ≈ 5.75:1 ✓
              "text-destructive hover:bg-destructive/8"
            )}
          >
            Delete
          </button>
        </div>
      </div>

      {/* ── Inline replace-validation error ──────────────────────────────── */}
      {replaceError && (
        <p
          id={errorId}
          role="alert"
          aria-live="assertive"
          className={cn(
            // text-destructive/80 ≈ 2.95:1 on paper (FAILS AA); full opacity ≈ 5.75:1 ✓
            "text-xs text-destructive",
            "font-sans leading-snug"
          )}
        >
          {replaceError}
        </p>
      )}

      {/*
       * Hidden file input for Replace.
       * accept attribute mirrors ACCEPTED_EXTENSIONS (req admin-console-016).
       * tabIndex=-1 keeps it out of the natural tab order — the visible
       * Replace button is the keyboard entry point (req admin-console-019).
       */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.md,.txt"
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        onChange={handleFileChange}
      />
    </article>
  )
}

export default DocumentCard
