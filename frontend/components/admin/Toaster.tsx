"use client"

/**
 * Toaster + useToast — in-house, zero-dependency toast system.
 *
 * Design decisions (admin-console design.md):
 *   - Module-level store so AdminConsole simply mounts <Toaster /> anywhere and
 *     any client component calls useToast().addToast() without a Provider wrapper.
 *   - aria-live="polite" region announces new toasts to assistive technology
 *     without interrupting ongoing screen-reader speech (req admin-console-020).
 *   - success = quiet ink-on-paper (foreground text, border hairline, no color emphasis).
 *   - error  = calm destructive (muted terracotta tint, NOT an alarm banner).
 *   - Auto-dismiss at 5 s; manually dismissible via button or keyboard (Escape / Enter / Space).
 *   - All transitions disabled when prefers-reduced-motion: reduce is set.
 *
 * req: admin-console-017, admin-console-018 (toast on confirm/cancel paths), admin-console-020
 */

import * as React from "react"
import { cn } from "@/lib/utils"

// ── Data model ────────────────────────────────────────────────────────────────

export interface Toast {
  id: string
  kind: "success" | "error"
  message: string
}

// ── Module-level store ────────────────────────────────────────────────────────
// A lightweight reactive store: plain array + a Set of listener callbacks.
// Using module scope (not React state) means addToast/removeToast can be
// called from anywhere (hooks, event handlers) without needing a context ref.

let _toasts: Toast[] = []
const _listeners = new Set<() => void>()

function _notify() {
  _listeners.forEach((fn) => fn())
}

/** Unique id generation — timestamp + short random suffix. */
function _uid(): string {
  return `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

const AUTO_DISMISS_MS = 5_000

function _removeToast(id: string) {
  _toasts = _toasts.filter((t) => t.id !== id)
  _notify()
}

function _addToast(kind: Toast["kind"], message: string): void {
  const id = _uid()
  _toasts = [..._toasts, { id, kind, message }]
  _notify()
  setTimeout(() => _removeToast(id), AUTO_DISMISS_MS)
}

// ── Internal store hook ───────────────────────────────────────────────────────

function useToastStore(): Toast[] {
  const [, rerender] = React.useReducer((x: number) => x + 1, 0)

  React.useEffect(() => {
    _listeners.add(rerender)
    return () => {
      _listeners.delete(rerender)
    }
  }, [])

  return _toasts
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * useToast — returns { addToast } for triggering toasts from any client component.
 *
 * Usage:
 *   const { addToast } = useToast()
 *   addToast('success', 'Document uploaded.')
 *   addToast('error', 'Upload failed — please try again.')
 *
 * req: admin-console-009 (success toast), admin-console-010 (error toast),
 *      admin-console-017 (delete success toast), admin-console-020 (aria-live)
 */
export function useToast() {
  return { addToast: _addToast }
}

// ── Toast item ────────────────────────────────────────────────────────────────

interface ToastItemProps {
  toast: Toast
  onDismiss: (id: string) => void
}

function ToastItem({ toast, onDismiss }: ToastItemProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      onDismiss(toast.id)
    }
  }

  const handleDismissKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      onDismiss(toast.id)
    }
  }

  return (
    <div
      role="status"
      aria-atomic="true"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className={cn(
        // Layout
        "pointer-events-auto flex items-start gap-3 rounded-lg border px-4 py-3 text-sm",
        // Typography
        "font-sans leading-snug",
        // Motion — fade + slide up; disabled under prefers-reduced-motion
        "translate-y-0 opacity-100 transition-all duration-300 ease-out",
        "motion-reduce:transition-none motion-reduce:transform-none",
        // Focus ring for keyboard users
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        // Kind-specific styling: calm, never alarming
        toast.kind === "success"
          ? [
              // Success: ink-on-paper — uses the default surface; just a hairline border
              "bg-background border-border text-foreground",
            ]
          : [
              // Error: calm destructive tint (muted terracotta), NOT a red alarm banner
              "bg-destructive/5 border-destructive/25 text-foreground",
            ]
      )}
    >
      {/* Kind indicator — icon paired with color so meaning isn't color-only (WCAG 1.4.1) */}
      <span aria-hidden="true" className="mt-px shrink-0 select-none text-base leading-none">
        {toast.kind === "success" ? "✓" : "·"}
      </span>

      <span className="flex-1">{toast.message}</span>

      {/*
       * Dismiss button — text-muted-foreground (#6B6259) at full opacity.
       *
       * Previously used opacity-50 which dropped the × icon's effective
       * contrast to ~2.0:1 on paper — fails WCAG SC 1.4.11 (Non-text
       * Contrast, 3:1 for UI components). Full opacity gives ~5.26:1 ✓.
       * The muted color already provides the desired visual quietness
       * without an additional opacity layer. req: admin-console-021
       */}
      <button
        type="button"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(toast.id)}
        onKeyDown={handleDismissKeyDown}
        className={cn(
          "shrink-0 self-start rounded p-0.5 text-muted-foreground",
          "transition-colors duration-150 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
          "motion-reduce:transition-none"
        )}
      >
        {/* Inline SVG — no extra dep required */}
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          aria-hidden="true"
          focusable="false"
        >
          <path
            d="M1 1l12 12M13 1L1 13"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>
    </div>
  )
}

// ── Toaster — the aria-live region ───────────────────────────────────────────

/**
 * <Toaster /> — mount once inside the AdminConsole client island.
 * Renders an aria-live="polite" region at the bottom-right of the viewport.
 * No props needed; it subscribes to the module-level toast store automatically.
 *
 * req: admin-console-020 (aria-live announcements for status changes and toasts)
 */
export function Toaster() {
  const toasts = useToastStore()

  return (
    /*
     * aria-live="polite" — announced after current speech finishes, not immediately.
     * aria-atomic="false" — each toast child is announced individually as it appears.
     * role="log"          — semantic region for sequential informational messages.
     * The region is always in the DOM (even when empty) so the browser registers
     * the live region before the first toast fires.
     */
    <div
      aria-live="polite"
      aria-atomic="false"
      role="log"
      aria-label="Notifications"
      className={cn(
        "pointer-events-none fixed bottom-4 right-4 z-[100]",
        "flex w-full max-w-sm flex-col gap-2"
      )}
    >
      {toasts.map((toast) => (
        <ToastItem
          key={toast.id}
          toast={toast}
          onDismiss={_removeToast}
        />
      ))}
    </div>
  )
}
