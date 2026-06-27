/**
 * components/admin/StatusPill.tsx
 *
 * Token-styled status pill for document ingestion states.
 * Pure presentational server component — no "use client" directive needed.
 *
 * Four states: pending | ingesting | ready | failed.
 *   - pending   : muted grey, hollow ring dot, label "Pending"
 *   - ingesting : muted grey, pulsing dot (CSS animate-pulse, auto-disabled
 *                 under prefers-reduced-motion via globals.css), label "Ingesting"
 *   - ready     : accent (aubergine) tint, filled dot, label "Ready"
 *   - failed    : muted terracotta tint at LOW emphasis, X dot, label "Failed"
 *                 — never an alarm, never shows a reason (req admin-console-015)
 *
 * WCAG 1.4.1: meaning is NOT conveyed by color alone — every state has a
 * distinct label + a shaped/animated dot as a non-color cue.
 *
 * req: admin-console-011, admin-console-015
 */

import { cn } from "@/lib/utils";
import type { DocStatus } from "@/lib/adminApi";

// Re-export so sibling components can import from here without a second import path.
export type { DocStatus };

// ---------------------------------------------------------------------------
// Status configuration table
// ---------------------------------------------------------------------------

interface StatusConfig {
  /** English label — satisfies admin-console-022 (English-only console). */
  label: string;
  /** Tailwind classes for the outer pill span. */
  pillCn: string;
  /** Tailwind classes for the dot indicator. */
  dotCn: string;
  /**
   * Whether the dot pulses to signal active work.
   * animate-pulse is automatically suppressed by globals.css under
   * prefers-reduced-motion: reduce (req admin-console-019, frontend-shell-018).
   */
  dotPulse: boolean;
  /** Non-color indicator rendered inside the dot area. */
  dotShape: "ring" | "solid" | "check" | "x";
  /** Accessible description of the status for screen readers. */
  ariaLabel: string;
}

const STATUS_CONFIG: Record<DocStatus, StatusConfig> = {
  pending: {
    label: "Pending",
    pillCn:
      "bg-muted border-border text-muted-foreground",
    dotCn: "border border-muted-foreground/50",
    dotPulse: false,
    dotShape: "ring",
    ariaLabel: "Status: pending — waiting to ingest",
  },
  ingesting: {
    label: "Ingesting",
    pillCn:
      "bg-muted border-border text-muted-foreground",
    dotCn: "bg-muted-foreground/70 animate-pulse",
    dotPulse: true,
    dotShape: "solid",
    ariaLabel: "Status: ingesting — processing now",
  },
  ready: {
    label: "Ready",
    pillCn:
      "bg-primary/10 border-primary/25 text-primary",
    dotCn: "bg-primary",
    dotPulse: false,
    dotShape: "check",
    ariaLabel: "Status: ready — available in the corpus",
  },
  failed: {
    // Calm, muted terracotta at low emphasis.
    // Uses text-foreground (ink) for high contrast on the tinted bg —
    // never a red alarm banner, no reason shown (req admin-console-015).
    label: "Failed",
    pillCn:
      "bg-destructive/8 border-destructive/20 text-foreground",
    dotCn: "bg-destructive/55",
    dotPulse: false,
    dotShape: "x",
    ariaLabel: "Status: failed — ingestion did not complete",
  },
};

// ---------------------------------------------------------------------------
// Dot indicator sub-component
// ---------------------------------------------------------------------------

function Dot({
  shape,
  dotCn,
}: {
  shape: StatusConfig["dotShape"];
  dotCn: string;
}) {
  // All dots share a fixed 6×6 px canvas; shape differentiates state visually.
  const base = "inline-flex shrink-0 size-1.5 rounded-full items-center justify-center";

  if (shape === "ring") {
    // Hollow ring — pending: not started, empty inside
    return (
      <span
        aria-hidden="true"
        className={cn(base, dotCn)}
        style={{ background: "transparent" }}
      />
    );
  }

  if (shape === "check") {
    // Filled dot with a tiny checkmark groove — ready state
    return (
      <span aria-hidden="true" className={cn(base, dotCn)}>
        {/* Tiny SVG check renders at 6×6; crisp at this size */}
        <svg
          viewBox="0 0 6 6"
          aria-hidden="true"
          className="size-full"
          fill="none"
        >
          <path
            d="M1 3 L2.5 4.5 L5 1.5"
            stroke="currentColor"
            strokeWidth="1"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }

  if (shape === "x") {
    // Filled dot with a small × — failed state, calm (muted terracotta)
    return (
      <span aria-hidden="true" className={cn(base, dotCn)}>
        <svg
          viewBox="0 0 6 6"
          aria-hidden="true"
          className="size-full"
          fill="none"
        >
          <path
            d="M1.5 1.5 L4.5 4.5 M4.5 1.5 L1.5 4.5"
            stroke="currentColor"
            strokeWidth="1"
            strokeLinecap="round"
          />
        </svg>
      </span>
    );
  }

  // solid — ingesting (pulsing) or any other solid dot
  return <span aria-hidden="true" className={cn(base, dotCn)} />;
}

// ---------------------------------------------------------------------------
// StatusPill
// ---------------------------------------------------------------------------

export interface StatusPillProps {
  status: DocStatus;
  className?: string;
}

/**
 * StatusPill renders a small token-styled pill for a document's ingestion
 * status. It uses design-system tokens exclusively (no hard-coded colors)
 * and pairs every color cue with a distinct label + dot shape (WCAG 1.4.1).
 *
 * req: admin-console-011 — name + status pill per document
 * req: admin-console-015 — failed is calm, muted, no reason shown
 */
export function StatusPill({ status, className }: StatusPillProps) {
  const cfg = STATUS_CONFIG[status];

  return (
    <span
      role="status"
      aria-label={cfg.ariaLabel}
      className={cn(
        // Base pill geometry — matches the project's small-badge scale
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
        // Typographic scale: mono face for status tokens (per design.md)
        "font-mono text-[0.7rem] font-medium leading-none whitespace-nowrap",
        // Calm cross-fade when status changes (e.g. ingesting → ready).
        // Transitions background-color, border-color, and color between states.
        // Disabled by the global prefers-reduced-motion override in globals.css
        // and by the explicit motion-reduce utility below. (req admin-console-021)
        "transition-colors duration-200 motion-reduce:transition-none",
        // Per-status color + border
        cfg.pillCn,
        className
      )}
    >
      <Dot shape={cfg.dotShape} dotCn={cfg.dotCn} />
      {cfg.label}
    </span>
  );
}

export default StatusPill;
