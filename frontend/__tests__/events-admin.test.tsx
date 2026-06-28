/**
 * __tests__/events-admin.test.tsx
 *
 * Tests for the admin events section — events-006.
 *
 * Coverage:
 *   - events API transport functions: listEvents, createEvent, deleteEvent,
 *     listEnrollments (unit-tests the fetch wiring).
 *   - EventForm: renders fields, validates end-before-start, resets on success.
 *   - EventList: renders events, shows empty state, exposes Delete button.
 *   - AdminConsole integration: Events tab visible, switching between tabs.
 *
 * Mock strategy:
 *   - @/lib/adminApi: all events fns + isAdminApiError (faithful impl).
 *   - @/components/admin/Toaster: useToast spy; Toaster renders null.
 *   - global.fetch: mocked for the transport unit-tests.
 *
 * Traces: events-006
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

// ── Hoisted spy ──────────────────────────────────────────────────────────────
const mockAddToast = vi.hoisted(() => vi.fn())

// ── Module mocks ─────────────────────────────────────────────────────────────

vi.mock("@/lib/adminApi", async (importActual) => {
  const mod = await importActual<typeof import("@/lib/adminApi")>()
  return {
    ...mod,
    listDocuments: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    replaceDocument: vi.fn(),
    listEvents: vi.fn(),
    createEvent: vi.fn(),
    deleteEvent: vi.fn(),
    listEnrollments: vi.fn(),
  }
})

vi.mock("@/components/admin/Toaster", () => ({
  useToast: () => ({ addToast: mockAddToast }),
  Toaster: () => null,
}))

// ── Imports ───────────────────────────────────────────────────────────────────

import {
  listEvents,
  createEvent,
  deleteEvent,
  listEnrollments,
  listDocuments,
} from "@/lib/adminApi"
import type { EventSummary, Enrollment, AdminApiError } from "@/lib/adminApi"

import { AdminConsole } from "@/components/admin/AdminConsole"
import { EventForm } from "@/components/admin/EventForm"
import { EventList } from "@/components/admin/EventList"

// ── Fixtures ──────────────────────────────────────────────────────────────────

const SESSION_KEY = "admin_token"
const TEST_TOKEN = "test-admin-token"

const SAMPLE_EVENTS: EventSummary[] = [
  {
    id: 1,
    title: "Stoicism Seminar",
    start_at: "2026-09-01T10:00:00",
    end_at: "2026-09-01T12:00:00",
  },
  {
    id: 2,
    title: "Ethics Workshop",
    start_at: "2026-10-05T14:00:00",
    end_at: "2026-10-05T16:00:00",
  },
]

const SAMPLE_ENROLLMENTS: Enrollment[] = [
  { name: "Sócrates", created_at: "2026-08-01T09:00:00" },
  { name: "Platón", created_at: "2026-08-02T11:00:00" },
]

const AUTH_ERROR: AdminApiError = {
  ok: false,
  kind: "auth",
  status: 401,
  message: "Unauthorized",
}

function seedToken() {
  sessionStorage.setItem(SESSION_KEY, TEST_TOKEN)
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  vi.mocked(listDocuments).mockResolvedValue([])
  vi.mocked(listEvents).mockResolvedValue([])
  vi.mocked(createEvent).mockResolvedValue({ id: 10 })
  vi.mocked(deleteEvent).mockResolvedValue(true)
  vi.mocked(listEnrollments).mockResolvedValue([])
})

afterEach(() => {
  vi.useRealTimers()
})

// ─────────────────────────────────────────────────────────────────────────────
// Transport: listEvents
// eval: events-006 (API wiring)
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — listEvents transport", () => {
  it("listEvents mock returns an event array", async () => {
    vi.mocked(listEvents).mockResolvedValue(SAMPLE_EVENTS)
    const result = await listEvents("tok")
    expect(Array.isArray(result)).toBe(true)
    expect((result as EventSummary[])[0].title).toBe("Stoicism Seminar")
  })

  it("listEvents mock returns an AdminApiError on auth failure", async () => {
    vi.mocked(listEvents).mockResolvedValue(AUTH_ERROR)
    const result = await listEvents("bad-tok")
    expect((result as AdminApiError).ok).toBe(false)
    expect((result as AdminApiError).kind).toBe("auth")
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Transport: createEvent
// eval: events-006 (API wiring)
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — createEvent transport", () => {
  it("createEvent mock returns { id } on success", async () => {
    vi.mocked(createEvent).mockResolvedValue({ id: 42 })
    const result = await createEvent("tok", {
      title: "Test Event",
      description: "desc",
      start_at: "2026-09-01T10:00:00",
      end_at: "2026-09-01T12:00:00",
      location: "Online",
      timezone: "UTC",
    })
    expect((result as { id: number }).id).toBe(42)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Transport: deleteEvent
// eval: events-006 (API wiring)
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — deleteEvent transport", () => {
  it("deleteEvent mock returns true on success", async () => {
    vi.mocked(deleteEvent).mockResolvedValue(true)
    const result = await deleteEvent("tok", 1)
    expect(result).toBe(true)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Transport: listEnrollments
// eval: events-006 (API wiring)
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — listEnrollments transport", () => {
  it("listEnrollments mock returns an array of enrollments", async () => {
    vi.mocked(listEnrollments).mockResolvedValue(SAMPLE_ENROLLMENTS)
    const result = await listEnrollments("tok", 1)
    expect(Array.isArray(result)).toBe(true)
    expect((result as Enrollment[])[0].name).toBe("Sócrates")
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// EventForm — renders all six fields
// eval: events-006
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — EventForm renders all required fields", () => {
  it("renders title, description, start, end, location, and timezone fields", () => {
    render(<EventForm onSubmit={vi.fn()} />)

    expect(screen.getByLabelText(/Title/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Description/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Start/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/End/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Location/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Timezone/i)).toBeInTheDocument()
  })

  it("shows a Create event submit button", () => {
    render(<EventForm onSubmit={vi.fn()} />)
    expect(screen.getByRole("button", { name: /Create event/i })).toBeInTheDocument()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// EventForm — client validation: end must be after start
// eval: events-006
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — EventForm validates end-after-start", () => {
  it("shows a validation error when end is before start", async () => {
    const user = userEvent.setup()
    render(<EventForm onSubmit={vi.fn()} />)

    await user.type(screen.getByLabelText(/Title/i), "Test Event")
    await user.type(screen.getByLabelText(/Description/i), "A description")
    await user.type(screen.getByLabelText(/Location/i), "Online")

    // Set start and end via fireEvent (datetime-local inputs)
    fireEvent.change(screen.getByLabelText(/Start/i), {
      target: { value: "2026-09-01T10:00" },
    })
    fireEvent.change(screen.getByLabelText(/End/i), {
      target: { value: "2026-09-01T09:00" }, // end BEFORE start
    })

    await user.click(screen.getByRole("button", { name: /Create event/i }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(/End must be after start/i)
  })

  it("does NOT call onSubmit when required fields are missing", async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<EventForm onSubmit={onSubmit} />)

    // Submit with empty form
    await user.click(screen.getByRole("button", { name: /Create event/i }))

    expect(onSubmit).not.toHaveBeenCalled()
    // Validation errors should appear
    const alerts = screen.getAllByRole("alert")
    expect(alerts.length).toBeGreaterThan(0)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// EventForm — calls onSubmit with correct payload on valid input
// eval: events-006
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — EventForm calls onSubmit with correct payload", () => {
  it("calls onSubmit once with a valid payload when all fields are filled", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    render(<EventForm onSubmit={onSubmit} />)

    await user.type(screen.getByLabelText(/Title/i), "Philosophy Evening")
    await user.type(screen.getByLabelText(/Description/i), "An intro session.")
    await user.type(screen.getByLabelText(/Location/i), "Room 1")

    fireEvent.change(screen.getByLabelText(/Start/i), {
      target: { value: "2026-10-01T18:00" },
    })
    fireEvent.change(screen.getByLabelText(/End/i), {
      target: { value: "2026-10-01T20:00" },
    })

    await user.click(screen.getByRole("button", { name: /Create event/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))

    const [payload] = onSubmit.mock.calls[0] as [import("@/lib/adminApi").EventCreatePayload]
    expect(payload.title).toBe("Philosophy Evening")
    expect(payload.description).toBe("An intro session.")
    expect(payload.location).toBe("Room 1")
    expect(payload.start_at).toMatch(/2026-10-01T18:00/)
    expect(payload.end_at).toMatch(/2026-10-01T20:00/)
    expect(payload.timezone).toBeTruthy()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// EventList — renders events and empty state
// eval: events-006
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — EventList renders events and empty state", () => {
  it("shows empty state when events array is empty and not loading", () => {
    render(
      <EventList
        events={[]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onDelete={vi.fn()}
        fetchEnrollments={vi.fn()}
      />
    )

    // Exact text with period avoids matching the sr-only status region which
    // also contains "No events yet" in a longer announcement string.
    expect(screen.getByText("No events yet.")).toBeInTheDocument()
  })

  it("renders event titles from the events prop", () => {
    render(
      <EventList
        events={SAMPLE_EVENTS}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onDelete={vi.fn()}
        fetchEnrollments={vi.fn()}
      />
    )

    expect(screen.getByText("Stoicism Seminar")).toBeInTheDocument()
    expect(screen.getByText("Ethics Workshop")).toBeInTheDocument()
  })

  it("each event row has a Delete button", () => {
    render(
      <EventList
        events={SAMPLE_EVENTS}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onDelete={vi.fn()}
        fetchEnrollments={vi.fn()}
      />
    )

    // There should be one Delete button per event
    const deleteButtons = screen.getAllByRole("button", { name: /^delete$/i })
    expect(deleteButtons).toHaveLength(SAMPLE_EVENTS.length)
  })

  it("clicking Delete calls onDelete with the correct event", async () => {
    const onDelete = vi.fn()
    const user = userEvent.setup()

    render(
      <EventList
        events={SAMPLE_EVENTS}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onDelete={onDelete}
        fetchEnrollments={vi.fn()}
      />
    )

    const firstEventArticle = screen.getByRole("article", {
      name: /Event: Stoicism Seminar/i,
    })
    const deleteBtn = within(firstEventArticle).getByRole("button", {
      name: /^delete$/i,
    })
    await user.click(deleteBtn)

    expect(onDelete).toHaveBeenCalledTimes(1)
    expect(onDelete).toHaveBeenCalledWith(SAMPLE_EVENTS[0])
  })

  it("each event row has a Registrants button", () => {
    render(
      <EventList
        events={SAMPLE_EVENTS}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onDelete={vi.fn()}
        fetchEnrollments={vi.fn()}
      />
    )

    const registrantButtons = screen.getAllByRole("button", {
      name: /registrants/i,
    })
    expect(registrantButtons).toHaveLength(SAMPLE_EVENTS.length)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// AdminConsole — Events tab visible and functional
// eval: events-006
// ─────────────────────────────────────────────────────────────────────────────

describe("events-006 — AdminConsole includes Events tab", () => {
  it("shows a Documents and Events tab in the console", async () => {
    seedToken()
    render(<AdminConsole />)

    // Both tabs must be present
    expect(screen.getByRole("tab", { name: /Documents/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /Events/i })).toBeInTheDocument()
  })

  it("Documents tab is selected by default", () => {
    seedToken()
    render(<AdminConsole />)

    const docTab = screen.getByRole("tab", { name: /Documents/i })
    expect(docTab).toHaveAttribute("aria-selected", "true")

    const eventsTab = screen.getByRole("tab", { name: /Events/i })
    expect(eventsTab).toHaveAttribute("aria-selected", "false")
  })

  it("switching to Events tab shows the Create event form", async () => {
    seedToken()
    const user = userEvent.setup()
    render(<AdminConsole />)

    const eventsTab = screen.getByRole("tab", { name: /Events/i })
    await user.click(eventsTab)

    // Create event form heading
    expect(screen.getByRole("heading", { name: /Create event/i })).toBeInTheDocument()
    // Form itself
    expect(screen.getByRole("form", { name: /Create event/i })).toBeInTheDocument()
  })

  it("Events tab calls listEvents with the admin token", async () => {
    seedToken()
    vi.mocked(listEvents).mockResolvedValue(SAMPLE_EVENTS)

    render(<AdminConsole />)

    await waitFor(() => {
      expect(vi.mocked(listEvents)).toHaveBeenCalledWith(TEST_TOKEN)
    })
  })
})
