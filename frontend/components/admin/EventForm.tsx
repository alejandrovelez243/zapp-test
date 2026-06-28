"use client"

/**
 * components/admin/EventForm.tsx
 *
 * Create-event form for the admin events section.
 *
 * Fields (all required):
 *   title       — text
 *   description — textarea
 *   start_at    — datetime-local → ISO 8601 string sent to the backend
 *   end_at      — datetime-local → ISO 8601 string; must be after start_at
 *   location    — text
 *   timezone    — select of curated IANA timezone strings
 *
 * Client-side validation gates submission:
 *   - All fields non-empty.
 *   - end_at must be strictly after start_at (events-006 requirement: sane dates).
 * Server errors (non-2xx responses) are surfaced inline below the submit button.
 *
 * Design: editorial, typographic, no heavy card shadow. Consistent with the
 * existing form aesthetics in TokenGate and the broader admin console.
 *
 * req: events-001, events-006
 */

import * as React from "react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import type { EventCreatePayload } from "@/lib/adminApi"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Curated IANA timezones covering the key ES / EN / PT audience.
 * Displayed as "Region/City (UTC offset-label)".
 */
const IANA_TIMEZONES: { value: string; label: string }[] = [
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "America/New York (ET)" },
  { value: "America/Chicago", label: "America/Chicago (CT)" },
  { value: "America/Denver", label: "America/Denver (MT)" },
  { value: "America/Los_Angeles", label: "America/Los Angeles (PT)" },
  { value: "America/Mexico_City", label: "America/Mexico City (CST)" },
  { value: "America/Bogota", label: "America/Bogota (COT)" },
  { value: "America/Lima", label: "America/Lima (PET)" },
  { value: "America/Santiago", label: "America/Santiago (CLT)" },
  { value: "America/Argentina/Buenos_Aires", label: "America/Buenos Aires (ART)" },
  { value: "America/Sao_Paulo", label: "America/Sao Paulo (BRT)" },
  { value: "America/Caracas", label: "America/Caracas (VET)" },
  { value: "Europe/Lisbon", label: "Europe/Lisbon (WET)" },
  { value: "Europe/London", label: "Europe/London (GMT)" },
  { value: "Europe/Madrid", label: "Europe/Madrid (CET)" },
  { value: "Europe/Paris", label: "Europe/Paris (CET)" },
  { value: "Europe/Berlin", label: "Europe/Berlin (CET)" },
  { value: "Europe/Rome", label: "Europe/Rome (CET)" },
  { value: "Africa/Lagos", label: "Africa/Lagos (WAT)" },
  { value: "Africa/Nairobi", label: "Africa/Nairobi (EAT)" },
  { value: "Asia/Dubai", label: "Asia/Dubai (GST)" },
  { value: "Asia/Tokyo", label: "Asia/Tokyo (JST)" },
  { value: "Asia/Singapore", label: "Asia/Singapore (SGT)" },
  { value: "Australia/Sydney", label: "Australia/Sydney (AEDT)" },
  { value: "Pacific/Auckland", label: "Pacific/Auckland (NZST)" },
  { value: "Pacific/Honolulu", label: "Pacific/Honolulu (HST)" },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert a datetime-local value ("YYYY-MM-DDTHH:MM") to an ISO-8601 string. */
function localToIso(value: string): string {
  // datetime-local gives "YYYY-MM-DDTHH:MM"; we need "YYYY-MM-DDTHH:MM:00"
  // The backend expects ISO 8601; appending ":00" makes it fully valid.
  return value.length === 16 ? `${value}:00` : value
}

// ---------------------------------------------------------------------------
// Shared field wrapper
// ---------------------------------------------------------------------------

interface FieldProps {
  id: string
  label: string
  error?: string | null
  children: React.ReactNode
  className?: string
}

function Field({ id, label, error, children, className }: FieldProps) {
  const errorId = `${id}-error`
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label
        htmlFor={id}
        className="block text-sm font-medium text-foreground"
      >
        {label}
      </label>
      {/* Clone child to inject aria-describedby when there's an error */}
      {React.Children.map(children, (child) => {
        if (React.isValidElement(child)) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          return React.cloneElement(child as React.ReactElement<any>, {
            id,
            "aria-describedby": error ? errorId : undefined,
            "aria-invalid": error ? true : undefined,
          })
        }
        return child
      })}
      {error && (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Input / Textarea / Select base styles
// ---------------------------------------------------------------------------

const inputCn = cn(
  "block w-full rounded-md border bg-background px-3 py-2",
  "text-sm font-sans text-foreground placeholder:text-muted-foreground",
  "border-border outline-none transition-shadow duration-150",
  "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
)

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface EventFormProps {
  /**
   * Called with a validated payload when the form is submitted.
   * Returns true on success (form resets), false on server error.
   */
  onSubmit: (payload: EventCreatePayload) => Promise<boolean>
}

// ---------------------------------------------------------------------------
// EventForm
// ---------------------------------------------------------------------------

/**
 * EventForm — create-event form used in the admin events section.
 *
 * Presentational: it calls onSubmit(payload) and the parent hook (useEvents)
 * issues the POST request. This keeps the form deterministically testable.
 *
 * req: events-001, events-006
 */
export function EventForm({ onSubmit }: EventFormProps) {
  // ── Form state ───────────────────────────────────────────────────────────
  const [title, setTitle] = React.useState("")
  const [description, setDescription] = React.useState("")
  const [startAt, setStartAt] = React.useState("")
  const [endAt, setEndAt] = React.useState("")
  const [location, setLocation] = React.useState("")
  const [timezone, setTimezone] = React.useState("UTC")

  // ── Validation errors ────────────────────────────────────────────────────
  const [errors, setErrors] = React.useState<Partial<Record<string, string>>>({})
  const [submitError, setSubmitError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  // ── Unique ids ───────────────────────────────────────────────────────────
  const titleId = React.useId()
  const descId = React.useId()
  const startId = React.useId()
  const endId = React.useId()
  const locationId = React.useId()
  const tzId = React.useId()

  // ── Client validation ────────────────────────────────────────────────────
  function validate(): boolean {
    const next: Partial<Record<string, string>> = {}
    if (!title.trim()) next.title = "Title is required."
    if (!description.trim()) next.description = "Description is required."
    if (!startAt) next.startAt = "Start date and time are required."
    if (!endAt) next.endAt = "End date and time are required."
    else if (startAt && endAt <= startAt)
      next.endAt = "End must be after start."
    if (!location.trim()) next.location = "Location is required."
    if (!timezone) next.timezone = "Timezone is required."
    setErrors(next)
    return Object.keys(next).length === 0
  }

  // ── Submit ───────────────────────────────────────────────────────────────
  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setSubmitError(null)
    if (!validate()) return

    setBusy(true)
    const payload: EventCreatePayload = {
      title: title.trim(),
      description: description.trim(),
      start_at: localToIso(startAt),
      end_at: localToIso(endAt),
      location: location.trim(),
      timezone,
    }

    const ok = await onSubmit(payload)
    setBusy(false)

    if (ok) {
      // Reset form on success
      setTitle("")
      setDescription("")
      setStartAt("")
      setEndAt("")
      setLocation("")
      setTimezone("UTC")
      setErrors({})
    } else {
      setSubmitError("Event could not be saved — see the notification above.")
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      aria-label="Create event"
      className="flex flex-col gap-5"
    >
      {/* Title */}
      <Field id={titleId} label="Title" error={errors.title}>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Stoicism Seminar"
          className={inputCn}
        />
      </Field>

      {/* Description */}
      <Field id={descId} label="Description" error={errors.description}>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="A brief description of the event for students."
          className={cn(inputCn, "resize-y")}
        />
      </Field>

      {/* Start / End — two-column on wider viewports */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Field id={startId} label="Start" error={errors.startAt}>
          <input
            type="datetime-local"
            value={startAt}
            onChange={(e) => setStartAt(e.target.value)}
            className={inputCn}
          />
        </Field>

        <Field id={endId} label="End" error={errors.endAt}>
          <input
            type="datetime-local"
            value={endAt}
            onChange={(e) => setEndAt(e.target.value)}
            min={startAt || undefined}
            className={inputCn}
          />
        </Field>
      </div>

      {/* Location */}
      <Field id={locationId} label="Location" error={errors.location}>
        <input
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="e.g. Online via Zoom · Room 12, Athens Campus"
          className={inputCn}
        />
      </Field>

      {/* Timezone */}
      <Field id={tzId} label="Timezone" error={errors.timezone}>
        <select
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          className={cn(inputCn, "cursor-pointer")}
        >
          {IANA_TIMEZONES.map((tz) => (
            <option key={tz.value} value={tz.value}>
              {tz.label}
            </option>
          ))}
        </select>
      </Field>

      {/* Server-level error (e.g. validation from backend) */}
      {submitError && (
        <p
          role="alert"
          className="text-xs text-destructive"
        >
          {submitError}
        </p>
      )}

      {/* Submit */}
      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={busy}
          aria-busy={busy}
          className={cn(
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            busy && "cursor-not-allowed opacity-60"
          )}
        >
          {busy ? "Creating…" : "Create event"}
        </Button>
      </div>
    </form>
  )
}

export default EventForm
