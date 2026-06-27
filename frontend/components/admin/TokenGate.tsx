"use client"

/**
 * TokenGate — admin token-entry form.
 *
 * Shown WHILE no valid admin token is held (req admin-console-001).
 * Presentational: owns only the local input value; parent (AdminConsole)
 * owns token persistence and error resolution (req admin-console-003).
 *
 * Accessibility:
 *   - Visible focus ring on every interactive element via --ring (req admin-console-019).
 *   - Error message is role="alert" so screen readers announce it on mount (req admin-console-003).
 *   - Enter key on the input submits the form (keyboard operable, req admin-console-019).
 *   - Trims whitespace before calling onSubmit; ignores empty submission.
 *
 * Copy: English-only (internal staff tool, req admin-console-022).
 */

import * as React from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

// ── Props ─────────────────────────────────────────────────────────────────────

export interface TokenGateProps {
  /** Called with the trimmed token string when the admin submits. */
  onSubmit: (token: string) => void
  /**
   * Error message to display beneath the input.
   * Rendered in a role="alert" slot so assistive technology announces it.
   * Pass null or undefined to hide the slot entirely.
   */
  error?: string | null
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TokenGate({ onSubmit, error }: TokenGateProps) {
  const [value, setValue] = React.useState("")
  const inputId = React.useId()
  const errorId = React.useId()

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  return (
    /*
     * Full-page centering: flex column, vertically and horizontally centered.
     * Inherits the paper background (#F4EFE6) from <body>.
     * Narrow column (~44ch) with generous vertical breathing room.
     */
    <main
      className="flex min-h-screen flex-col items-center justify-center px-4"
      aria-label="Admin access"
    >
      <div className="w-full max-w-[22rem] space-y-8">

        {/* Editorial header ─────────────────────────────────────────────────── */}
        <header className="space-y-3">
          {/* Meander hairline above the heading */}
          <div className="rule-meander" aria-hidden="true" />

          {/*
           * Serif display heading — Newsreader via --font-heading.
           * font-heading is declared in globals.css @theme inline
           * and resolves to var(--font-serif) set by next/font.
           */}
          <h1 className="font-heading text-2xl font-medium tracking-tight text-foreground">
            Admin access
          </h1>

          <p className="text-sm text-muted-foreground">
            Enter your admin token to manage course documents.
          </p>
        </header>

        {/* Token entry form ─────────────────────────────────────────────────── */}
        <form onSubmit={handleSubmit} noValidate className="space-y-5">

          {/* Label + password input */}
          <div className="space-y-1.5">
            <label
              htmlFor={inputId}
              className="block text-sm font-medium text-foreground"
            >
              Admin token
            </label>

            <input
              id={inputId}
              type="password"
              autoComplete="current-password"
              spellCheck={false}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-describedby={error ? errorId : undefined}
              aria-invalid={!!error}
              placeholder="Enter your admin token"
              className={cn(
                // Layout & typography
                "block w-full rounded-md border bg-background px-3 py-2",
                "text-sm font-sans text-foreground placeholder:text-muted-foreground",
                // Border — warm grey hairline matching the design token
                "border-border",
                // Focus ring — aubergine via --ring, WCAG AA (8.7:1 on paper)
                "outline-none transition-shadow duration-150",
                "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
                // Error state — subtle destructive highlight (no red alarm banner)
                error && "border-destructive/60 focus-visible:ring-destructive/30"
              )}
            />

            {/*
             * Error message slot — role="alert" causes screen readers to announce
             * the message immediately when it appears (req admin-console-003).
             * Always in the DOM when error is set so the alert role fires on change.
             */}
            {error ? (
              <p
                id={errorId}
                role="alert"
                aria-live="assertive"
                className="text-xs text-destructive"
              >
                {error}
              </p>
            ) : null}
          </div>

          {/* Submit ─────────────────────────────────────────────────────────── */}
          {/*
           * shadcn Button (default variant) — aubergine background (#6E2C50),
           * ivory foreground (#F4EFE6), visible focus-visible ring via button.tsx.
           * type="submit" means Enter on the input triggers this (req admin-console-019).
           * Disabled while the input is empty (UI hint; trimming happens on submit).
           */}
          <Button
            type="submit"
            disabled={!value.trim()}
            className="w-full"
            size="lg"
          >
            Continue
          </Button>
        </form>

      </div>
    </main>
  )
}

export default TokenGate
