"use client"

/**
 * UploadDropzone — drag-and-drop / click / keyboard file-select zone.
 *
 * This component is ONLY responsible for collecting and validating a file.
 * It does NOT perform the upload; the parent (useDocuments.upload via AdminConsole)
 * owns that (per design.md: "emits a validated file; it does NOT perform the upload").
 *
 * Interaction modes (req admin-console-006):
 *   1. Drag a file from the OS and drop it on the zone.
 *   2. Click anywhere on the zone to open the system file picker.
 *   3. Focus the zone (Tab) and press Enter or Space to open the file picker.
 *
 * Validation (req admin-console-007):
 *   Accepted extensions: .pdf · .md · .txt only.
 *   Any other extension triggers an inline role="alert" rejection.
 *   onFile is NOT called on rejection — no upstream request is ever triggered.
 *
 * Busy state (req admin-console-008):
 *   When busy=true (upload in flight), the zone shows in-progress feedback and
 *   prevents re-trigger (pointer events disabled, keyboard blocked).
 *
 * Keyboard operability (req admin-console-019):
 *   tabIndex=0, role="button", Enter/Space open the hidden file input,
 *   visible --ring focus ring on focus-visible.
 *
 * Motion: calm border-color transition; disabled under prefers-reduced-motion.
 * Visual signature: .rule-meander-derived hairline that intensifies to the
 *   aubergine accent on drag-over (see design.md "Signature" note).
 *
 * req: admin-console-006, admin-console-007, admin-console-008, admin-console-019
 */

import * as React from "react"
import { cn } from "@/lib/utils"

// ── Constants ─────────────────────────────────────────────────────────────────

/** Accepted file extensions (req admin-console-007). Lower-case, dot-prefixed. */
const ACCEPTED_EXTENSIONS = [".pdf", ".md", ".txt"] as const
type AcceptedExtension = (typeof ACCEPTED_EXTENSIONS)[number]

/** Human-readable list for the rejection message and the hint copy. */
const ACCEPTED_LABEL = ACCEPTED_EXTENSIONS.join(", ")

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Extract the lower-cased dot-prefixed extension from a filename.
 * Returns empty string if the name has no extension.
 */
function getExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".")
  if (dotIndex === -1) return ""
  return filename.slice(dotIndex).toLowerCase()
}

/**
 * Validate a File object against the accepted extension list.
 * Returns null on success, or a human-readable error string on failure.
 * (req admin-console-007 — rejection before any request)
 */
function validateFile(file: File): string | null {
  const ext = getExtension(file.name)
  if ((ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) return null
  return ext
    ? `"${ext}" files are not accepted. Please upload a ${ACCEPTED_LABEL} file.`
    : `Cannot determine file type. Please upload a ${ACCEPTED_LABEL} file.`
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface UploadDropzoneProps {
  /**
   * Called with a validated File when the user successfully drops or selects one.
   * NOT called if the file extension is invalid (req admin-console-007).
   */
  onFile: (file: File) => void
  /**
   * When true the zone is visually and functionally disabled — no interaction.
   * Used externally (e.g., when the token gate is active or the feature is unavailable).
   */
  disabled?: boolean
  /**
   * When true an upload is in flight.
   * The zone shows a calm in-progress state and blocks re-trigger (req admin-console-008).
   * Does NOT disable the zone from a11y perspective — just prevents new file selection.
   */
  busy?: boolean
}

// ── Component ─────────────────────────────────────────────────────────────────

export function UploadDropzone({ onFile, disabled = false, busy = false }: UploadDropzoneProps) {
  // ── Refs ──────────────────────────────────────────────────────────────────
  const inputRef = React.useRef<HTMLInputElement>(null)
  const zoneRef = React.useRef<HTMLDivElement>(null)

  // ── State ─────────────────────────────────────────────────────────────────
  const [isDragOver, setIsDragOver] = React.useState(false)
  /**
   * Inline rejection message (req admin-console-007).
   * null = no error shown. Non-null = rendered as role="alert".
   */
  const [rejectionMessage, setRejectionMessage] = React.useState<string | null>(null)

  const errorId = React.useId()

  // ── Interaction guard ─────────────────────────────────────────────────────
  /** True when no interaction should be processed. */
  const isBlocked = disabled || busy

  // ── File processing ───────────────────────────────────────────────────────

  function processFile(file: File) {
    // Clear any prior rejection on each new attempt
    setRejectionMessage(null)

    const error = validateFile(file)
    if (error) {
      // Inline rejection — do NOT call onFile (req admin-console-007)
      setRejectionMessage(error)
      return
    }

    // Valid file — emit to parent
    onFile(file)
  }

  // ── Drag event handlers ───────────────────────────────────────────────────

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    if (isBlocked) return
    setIsDragOver(true)
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    // Only clear when leaving the zone itself, not a child element
    if (zoneRef.current && !zoneRef.current.contains(e.relatedTarget as Node | null)) {
      setIsDragOver(false)
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
    if (isBlocked) return

    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return
    // Use only the first file; silently ignore extras
    processFile(files[0])
  }

  // ── Click handler — open system file picker ───────────────────────────────

  function openPicker() {
    if (isBlocked) return
    inputRef.current?.click()
  }

  function handleClick() {
    openPicker()
  }

  // ── Keyboard handler — Enter or Space open the picker (req admin-console-006, 019) ──

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      openPicker()
    }
  }

  // ── Hidden file input change handler ─────────────────────────────────────

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0) return
    processFile(files[0])
    // Reset the input so selecting the same file again triggers onChange
    e.target.value = ""
  }

  // ── Derived visual state ──────────────────────────────────────────────────

  /** Border intensifies to aubergine when dragging over (design.md "Signature"). */
  const showAccentBorder = isDragOver && !isBlocked

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-2">
      {/*
       * Drop zone — the signature element of the admin console.
       *
       * role="button" + tabIndex=0 make it focusable and keyboard-operable
       * (req admin-console-019). aria-disabled communicates blocked state to AT.
       *
       * Border: warm-grey hairline (--border) by default; intensifies to the
       * aubergine accent (--ring / --primary) on drag-over — achieved via a
       * dashed border whose color transitions. Motion gated by motion-reduce
       * (req admin-console-021; globals.css @media prefers-reduced-motion covers
       * transition-duration globally, so the inline transition class is only needed
       * for the default path).
       */}
      <div
        ref={zoneRef}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={
          busy
            ? "Uploading — please wait"
            : "Upload a document. Drag and drop or press Enter to browse."
        }
        aria-describedby={rejectionMessage ? errorId : undefined}
        aria-disabled={isBlocked || undefined}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          // Layout — generous quiet drop target (design.md)
          "relative flex min-h-[10rem] w-full cursor-pointer flex-col items-center justify-center gap-3",
          "rounded-md border-2 border-dashed px-6 py-10 text-center",
          // Base border — warm grey hairline
          "border-border",
          // Calm transition on border-color (disabled by reduced-motion global override)
          "transition-colors duration-200 ease-in-out",
          // Drag-over state — aubergine accent border intensifies (req admin-console-006)
          showAccentBorder && "border-primary bg-primary/[0.03]",
          // Normal hover state — slight border darkening for discoverability
          !showAccentBorder && !isBlocked && "hover:border-primary/50",
          // Focus-visible ring — aubergine, WCAG AA (req admin-console-019)
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          // Disabled/busy states
          isBlocked && "cursor-not-allowed opacity-60",
          busy && "cursor-wait"
        )}
      >
        {busy ? (
          /*
           * In-progress state (req admin-console-008).
           * Calm visual — pulsing ellipsis (pulse disabled under reduced-motion
           * by the global @media override in globals.css).
           */
          <BusyIndicator />
        ) : (
          /*
           * Idle prompt — editorial, calm, invites action.
           */
          <IdlePrompt isDragOver={showAccentBorder} disabled={disabled} />
        )}
      </div>

      {/*
       * Inline rejection message (req admin-console-007).
       * role="alert" causes immediate announcement by screen readers.
       * Rendered below the zone so it is visually adjacent and in tab order.
       */}
      {rejectionMessage ? (
        <p
          id={errorId}
          role="alert"
          aria-live="assertive"
          className="text-xs text-destructive"
        >
          {rejectionMessage}
        </p>
      ) : null}

      {/*
       * Hidden file input — programmatically opened via click() (req admin-console-006).
       * accept attribute limits the system picker to the allowed extensions;
       * real validation still happens in processFile (picker can be bypassed
       * via drag-and-drop or path manipulation on some OSes).
       */}
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.md,.txt"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={handleInputChange}
      />
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * IdlePrompt — the default zone content when no upload is in flight.
 * Shows the meander hairline as a decorative top border and clear copy.
 */
function IdlePrompt({ isDragOver, disabled }: { isDragOver: boolean; disabled: boolean }) {
  return (
    <>
      {/* Upload icon — inline SVG, no dep */}
      <svg
        width="32"
        height="32"
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        focusable="false"
        className={cn(
          "transition-colors duration-200",
          isDragOver ? "text-primary" : "text-muted-foreground"
        )}
      >
        <path
          d="M10 21a7 7 0 1 1 3.18-13.24A6 6 0 0 1 25 14h1a4 4 0 0 1 0 8h-2"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M16 18v9M12 22l4-4 4 4"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      <div className="space-y-1">
        <p
          className={cn(
            "text-sm font-medium transition-colors duration-200",
            isDragOver ? "text-primary" : "text-foreground"
          )}
        >
          {isDragOver ? "Release to upload" : "Drag a document here"}
        </p>
        {!isDragOver && (
          <p className="text-xs text-muted-foreground">
            {disabled
              ? `Accepts ${ACCEPTED_LABEL}`
              : `or press Enter / click to browse — accepts ${ACCEPTED_LABEL}`}
          </p>
        )}
      </div>
    </>
  )
}

/**
 * BusyIndicator — calm in-progress feedback while upload is in flight.
 * A simple animated pulse; animation is silenced by the global reduced-motion rule.
 * (req admin-console-008)
 */
function BusyIndicator() {
  return (
    <>
      {/* Spinning upload indicator — CSS animation, silenced by reduced-motion */}
      <svg
        width="28"
        height="28"
        viewBox="0 0 28 28"
        fill="none"
        aria-hidden="true"
        focusable="false"
        className="animate-spin text-primary"
        style={{ animationDuration: "1.4s" }}
      >
        <circle
          cx="14"
          cy="14"
          r="11"
          stroke="currentColor"
          strokeWidth="2"
          strokeOpacity="0.2"
        />
        <path
          d="M14 3a11 11 0 0 1 11 11"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>

      <p className="text-sm font-medium text-foreground">Uploading&hellip;</p>
      <p className="text-xs text-muted-foreground">Please wait while the file is sent.</p>
    </>
  )
}

export default UploadDropzone
