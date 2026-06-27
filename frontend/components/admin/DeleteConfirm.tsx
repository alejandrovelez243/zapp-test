"use client"

/**
 * components/admin/DeleteConfirm.tsx
 *
 * A focus-trapped confirmation dialog for document deletion.
 *
 * Design intent:
 *   This is a destructive action gate, not an alarm. The modal is calm and
 *   typographically clear — a serif heading names the document, a single prose
 *   sentence explains the consequence, and two actions let the admin choose.
 *   Visual weight is low: no red fills, no warning icons, no heavy shadows.
 *   The accent (destructive token) is used only on the Delete button text to
 *   signal consequence without inducing panic.
 *
 * Focus management:
 *   Focus opens on Cancel (the safer default for a destructive dialog — req
 *   admin-console-019). Both buttons are reachable by Tab / Shift+Tab.
 *   Escape and backdrop click both map to onCancel (req admin-console-018).
 *
 * API contract:
 *   This component NEVER calls the network. It receives onConfirm / onCancel
 *   callbacks; the parent (useDocuments + AdminConsole) issues the DELETE after
 *   onConfirm fires (req admin-console-017, admin-console-018).
 *
 * req: admin-console-017 — explicit confirmation before DELETE
 * req: admin-console-018 — cancel / Escape sends nothing and keeps the doc
 * req: admin-console-019 — keyboard operable, visible focus indicator
 */

import * as React from "react"
import { cn } from "@/lib/utils"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import type { DocumentSummary } from "@/lib/adminApi"

// ── Props ─────────────────────────────────────────────────────────────────────

export interface DeleteConfirmProps {
  /**
   * Controls dialog visibility. Passed straight to the shadcn Dialog root as
   * the `open` prop (controlled mode).
   */
  open: boolean

  /**
   * The document to be deleted. When null the dialog renders nothing visible
   * (guarded below). Keeps the parent's state shape simple — it can set doc
   * first, then open=true, with no timing issue.
   */
  doc: DocumentSummary | null

  /**
   * Called when the admin clicks the Delete button.
   * The parent is responsible for issuing the DELETE request.
   * (req admin-console-017)
   */
  onConfirm: () => void

  /**
   * Called when the admin cancels — either by clicking Cancel, pressing
   * Escape, or clicking the backdrop. No network request is sent.
   * (req admin-console-018)
   */
  onCancel: () => void

  /**
   * When true, the Delete button shows an in-progress state and is disabled to
   * prevent double-fire. Cancel remains enabled so the admin can still escape
   * if something goes wrong.
   */
  busy?: boolean
}

// ── DeleteConfirm ──────────────────────────────────────────────────────────────

/**
 * DeleteConfirm is a controlled modal dialog that gates document deletion
 * behind an explicit admin confirmation.
 *
 * The shadcn `dialog` primitive (backed by @base-ui/react/dialog) provides:
 *   - Automatic focus trapping inside the dialog while open.
 *   - Escape-key handling (fires onOpenChange(false), mapped to onCancel).
 *   - Backdrop click handling (same path as Escape).
 *   - Correct aria-modal + role="dialog" on the popup element.
 *
 * The dialog hides the built-in close (×) button (showCloseButton={false})
 * because the two explicit action buttons are clearer UX for a confirm dialog.
 *
 * req: admin-console-017, admin-console-018, admin-console-019
 */
export function DeleteConfirm({
  open,
  doc,
  onConfirm,
  onCancel,
  busy = false,
}: DeleteConfirmProps) {
  /**
   * Map all dialog-dismiss signals (Escape, backdrop click) to onCancel.
   * base-ui calls onOpenChange(false) for all these paths.
   * (req admin-console-018)
   */
  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) onCancel()
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        // Hide the default × close button; Cancel button covers that affordance.
        showCloseButton={false}
        className={cn(
          // Narrow reading measure — keeps the message tightly focused
          "sm:max-w-md",
          // Paper background, ink text — classical palette (req admin-console-021)
          "bg-background text-foreground"
        )}
      >
        <DialogHeader>
          {/*
           * Title: names the document so the admin is certain what will be removed.
           * Uses font-heading (the project's serif display face) per design tokens.
           * (req admin-console-022 — English copy)
           */}
          <DialogTitle className="font-heading text-base leading-snug">
            {doc ? (
              <>
                Delete &ldquo;
                <span className="font-mono text-sm">{doc.name}</span>
                &rdquo;?
              </>
            ) : (
              "Delete document?"
            )}
          </DialogTitle>

          {/*
           * Description: one calm sentence. Explains consequence (removes it and
           * its chunks from the corpus) without alarm language.
           * (req admin-console-017, admin-console-022)
           */}
          <DialogDescription className="text-sm text-muted-foreground leading-relaxed">
            This removes the document and all its indexed chunks from the corpus.
            The action cannot be undone.
          </DialogDescription>
        </DialogHeader>

        {/*
         * Footer: Cancel (left / default) and Delete (right / destructive).
         *
         * Focus order is Cancel → Delete so that Tab from the last focusable
         * header element lands on Cancel first — the safer default action for
         * a destructive dialog (req admin-console-019).
         *
         * The autoFocus prop on Cancel ensures focus lands there when the dialog
         * opens, regardless of the broader tab order in the document.
         */}
        <DialogFooter className="gap-2">
          {/* Cancel — safe default; always enabled; Escape maps here too */}
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            // autoFocus: focus starts here when dialog opens (safer default)
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            className={cn(
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
            )}
          >
            Cancel
          </Button>

          {/*
           * Delete — destructive variant; disabled + aria-busy while busy.
           * Uses the `destructive` button variant which applies a muted red tint
           * (not a saturated fill) — calm per req admin-console-021.
           * (req admin-console-017 — confirm fires onConfirm, never the API)
           */}
          <Button
            type="button"
            variant="destructive"
            onClick={onConfirm}
            disabled={busy}
            aria-disabled={busy}
            aria-busy={busy}
            className={cn(
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              busy && "cursor-not-allowed opacity-60"
            )}
          >
            {busy ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default DeleteConfirm
