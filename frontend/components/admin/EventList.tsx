"use client"

/**
 * components/admin/EventList.tsx
 *
 * Admin events list: one row per EventSummary, each with a Delete button and
 * an expandable registrants panel (GET /events/{id}/enrollments).
 *
 * Layout (top → bottom per section):
 *   [header: "Events" heading · Refresh button]
 *   [error alert  — only when listError is set]
 *   [loading line — only while isLoading is true and list is empty]
 *   [empty state  — when events is empty, not loading, no error]
 *   [event rows   — one <EventRow> per event]
 *   [sr-only aria-live status region]
 *
 * Each EventRow:
 *   - Shows title + formatted start/end dates
 *   - Delete button → fires onDelete(event) (parent opens DeleteConfirm)
 *   - "Registrants" button → expands an inline panel fetching enrollments
 *     via the provided fetchEnrollments callback
 *
 * Design: editorial rows, no heavy cards, hairline borders, serif headings.
 *
 * req: events-003, events-004, events-005, events-006
 */

import * as React from "react"
import { cn } from "@/lib/utils"
import type { EventSummary, Enrollment } from "@/lib/adminApi"

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Format an ISO datetime string to a readable short form (locale-independent). */
function fmtDatetime(iso: string): string {
  try {
    const d = new Date(iso.endsWith("Z") ? iso : iso + "Z")
    return d.toLocaleString("en-GB", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    })
  } catch {
    return iso
  }
}

// ── Refresh icon ──────────────────────────────────────────────────────────────

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

// ── EventRow ──────────────────────────────────────────────────────────────────

interface EventRowProps {
  event: EventSummary
  busy: boolean
  onDelete: () => void
  fetchEnrollments: (id: number) => Promise<Enrollment[]>
}

function EventRow({ event, busy, onDelete, fetchEnrollments }: EventRowProps) {
  const [expanded, setExpanded] = React.useState(false)
  const [enrollments, setEnrollments] = React.useState<Enrollment[] | null>(null)
  const [enrollLoading, setEnrollLoading] = React.useState(false)
  const [enrollError, setEnrollError] = React.useState<string | null>(null)

  const registrantsPanelId = React.useId()

  async function toggleRegistrants() {
    if (expanded) {
      setExpanded(false)
      return
    }
    setExpanded(true)
    // Only fetch if not already loaded
    if (enrollments !== null) return
    setEnrollLoading(true)
    setEnrollError(null)
    try {
      const result = await fetchEnrollments(event.id)
      setEnrollments(result)
    } catch {
      setEnrollError("Failed to load registrants.")
    } finally {
      setEnrollLoading(false)
    }
  }

  return (
    <li
      aria-label={`Event: ${event.title}`}
    >
      {/* Main event row */}
      <article
        aria-label={`Event: ${event.title}`}
        className={cn(
          "rounded-md border border-border bg-background",
          "px-4 py-3 flex flex-col gap-1",
          "transition-colors duration-150",
          busy && "opacity-60"
        )}
      >
        {/* Title + actions row */}
        <div className="flex items-start justify-between gap-3">
          <span
            className={cn(
              "font-mono text-sm text-foreground leading-snug break-all flex-1 min-w-0"
            )}
          >
            {event.title}
          </span>

          <div className="flex items-center gap-2 shrink-0">
            {/* Registrants toggle */}
            <button
              type="button"
              onClick={toggleRegistrants}
              disabled={busy}
              aria-expanded={expanded}
              aria-controls={registrantsPanelId}
              className={cn(
                "inline-flex items-center gap-1 rounded px-2 py-1",
                "text-xs font-medium font-sans text-muted-foreground",
                "border border-transparent",
                "transition-colors duration-150 hover:text-foreground hover:bg-muted/50",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                "motion-reduce:transition-none",
                busy && "pointer-events-none cursor-not-allowed"
              )}
            >
              Registrants
              {/* Chevron toggles direction based on expanded state */}
              <svg
                width="10"
                height="10"
                viewBox="0 0 10 10"
                fill="none"
                aria-hidden="true"
                className={cn("transition-transform duration-150 motion-reduce:transition-none", expanded && "rotate-180")}
              >
                <path
                  d="M2 4l3 3 3-3"
                  stroke="currentColor"
                  strokeWidth="1.3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>

            {/* Delete */}
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              aria-disabled={busy}
              className={cn(
                "inline-flex items-center gap-1 rounded px-2 py-1",
                "text-xs font-medium font-sans text-muted-foreground",
                "border border-transparent",
                "transition-colors duration-150",
                "hover:text-destructive/80 hover:bg-destructive/5",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                "motion-reduce:transition-none",
                busy && "pointer-events-none cursor-not-allowed opacity-50"
              )}
            >
              Delete
            </button>
          </div>
        </div>

        {/* Start / End dates */}
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-0.5">
          <span className="text-xs font-sans text-muted-foreground">
            <span className="font-medium text-foreground/70">Start</span>{" "}
            {fmtDatetime(event.start_at)} UTC
          </span>
          <span className="text-xs font-sans text-muted-foreground">
            <span className="font-medium text-foreground/70">End</span>{" "}
            {fmtDatetime(event.end_at)} UTC
          </span>
        </div>
      </article>

      {/* Registrants panel */}
      <div
        id={registrantsPanelId}
        role="region"
        aria-label={`Registrants for ${event.title}`}
        aria-live="polite"
        className={cn(
          "overflow-hidden transition-all duration-200 motion-reduce:transition-none",
          expanded ? "max-h-96" : "max-h-0"
        )}
      >
        {expanded && (
          <div className="border border-t-0 border-border rounded-b-md bg-muted/30 px-4 py-3">
            {enrollLoading && (
              <p className="text-xs font-sans text-muted-foreground py-2">
                Loading registrants…
              </p>
            )}
            {enrollError && (
              <p role="alert" className="text-xs text-destructive py-2">
                {enrollError}
              </p>
            )}
            {!enrollLoading && !enrollError && enrollments !== null && (
              <>
                {enrollments.length === 0 ? (
                  <p className="text-xs font-sans text-muted-foreground italic py-2">
                    No registrants yet.
                  </p>
                ) : (
                  <ul
                    aria-label={`${enrollments.length} registrant${enrollments.length === 1 ? "" : "s"}`}
                    className="flex flex-col divide-y divide-border"
                  >
                    {enrollments.map((e, idx) => (
                      <li
                        key={idx}
                        className="flex items-baseline justify-between py-1.5 gap-3"
                      >
                        <span className="text-sm font-sans text-foreground">
                          {e.name}
                        </span>
                        <span className="text-xs font-mono text-muted-foreground shrink-0">
                          {fmtDatetime(e.created_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface EventListProps {
  events: EventSummary[]
  isLoading: boolean
  listError: string | null
  onRefresh(): void
  onDelete(event: EventSummary): void
  busyId?: number | null
  /**
   * Fetches enrollments for a given event id.
   * The parent (AdminConsole) supplies this bound to the admin token.
   * req: events-005, events-006
   */
  fetchEnrollments: (id: number) => Promise<Enrollment[]>
}

// ── EventList ─────────────────────────────────────────────────────────────────

/**
 * EventList renders the event catalog for the admin console events section.
 * Presentational: it never calls API functions directly; props come from AdminConsole.
 *
 * req: events-003, events-004, events-005, events-006
 */
export function EventList({
  events,
  isLoading,
  listError,
  onRefresh,
  onDelete,
  busyId = null,
  fetchEnrollments,
}: EventListProps) {
  const isEmpty = !isLoading && !listError && events.length === 0

  const announcement: string = isLoading
    ? "Loading events…"
    : listError
      ? "Failed to load events. See the error message."
      : events.length === 0
        ? "Event list loaded. No events yet."
        : `Event list refreshed. ${events.length} event${events.length === 1 ? "" : "s"}.`

  return (
    <section aria-label="Event list" className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-baseline justify-between gap-3">
        <h2
          className={cn(
            "font-serif text-xl font-normal leading-tight tracking-tight",
            "text-foreground"
          )}
        >
          Events
        </h2>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          aria-label="Refresh event list"
          aria-busy={isLoading}
          className={cn(
            "inline-flex items-center gap-1.5 rounded px-2.5 py-1",
            "text-xs font-medium font-sans text-muted-foreground",
            "border border-transparent",
            "transition-colors duration-150 hover:text-foreground hover:bg-muted/50",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            isLoading && "pointer-events-none opacity-40 cursor-not-allowed",
            "motion-reduce:transition-none"
          )}
        >
          <RefreshIcon
            className={cn(
              "size-3.5 shrink-0",
              isLoading && "animate-spin motion-reduce:animate-none"
            )}
          />
          {isLoading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Hairline rule */}
      <hr className="border-t border-border" aria-hidden="true" />

      {/* Error */}
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

      {/* Loading indicator (initial load only) */}
      {isLoading && events.length === 0 && (
        <p
          aria-hidden="true"
          className="py-8 text-center text-sm font-sans text-muted-foreground/70 select-none"
        >
          Loading…
        </p>
      )}

      {/* Empty state */}
      {isEmpty && (
        <div
          className="flex flex-col items-center gap-3 py-12 px-6 text-center"
          aria-label="No events yet"
        >
          <span aria-hidden="true" className="block w-8 border-t border-border" />
          <p className="font-serif text-lg font-normal text-foreground/70 leading-snug">
            No events yet.
          </p>
          <p className="max-w-[48ch] text-sm font-sans text-muted-foreground leading-relaxed">
            Use the form above to create the first event. It will appear here
            once saved, ready for students to discover in chat.
          </p>
        </div>
      )}

      {/* Event rows */}
      {!isLoading && events.length > 0 && (
        <ul
          aria-label={`${events.length} event${events.length === 1 ? "" : "s"}`}
          className="flex flex-col gap-2"
        >
          {events.map((event) => (
            <EventRow
              key={event.id}
              event={event}
              busy={busyId === event.id}
              onDelete={() => onDelete(event)}
              fetchEnrollments={fetchEnrollments}
            />
          ))}
        </ul>
      )}

      {/* sr-only aria-live status region */}
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

export default EventList
