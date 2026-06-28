/**
 * __tests__/admin-console.part2.test.tsx
 *
 * Component tests for the admin-console feature — Part 2 of 2.
 * Covers acceptance ids admin-console-012 … admin-console-022 ONLY.
 * (admin-console-001 … admin-console-011 live in a separate Part 1 file.)
 *
 * Mock strategy:
 *   - @/lib/adminApi — all four API functions (listDocuments, uploadDocument,
 *     replaceDocument, deleteDocument) are vi.fn(). isAdminApiError is
 *     implemented faithfully so useDocuments can narrow error vs. success returns.
 *   - sessionStorage seeded with admin_token so AdminConsole renders the console
 *     surface (not the TokenGate) in any test that needs the full console.
 *
 * Timer strategy for 012:
 *   vi.useFakeTimers() is used inside the polling test only; afterEach restores
 *   real timers so other tests are unaffected. Timer advancement is wrapped in
 *   await act(async () => { ... }) so React flushes state updates between ticks.
 *
 * Traces: admin-console-012 … admin-console-022
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import {
  render,
  screen,
  waitFor,
  act,
  within,
  fireEvent,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { readFileSync } from "fs"
import { resolve } from "path"

// ── Module mocks (hoisted before imports by Vitest) ────────────────────────

vi.mock("@/lib/adminApi", () => ({
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  replaceDocument: vi.fn(),
  deleteDocument: vi.fn(),
  // Events functions — also mocked so AdminConsole's useEvents hook does not
  // attempt real fetches when tests render the console. req: events-006.
  listEvents: vi.fn(),
  createEvent: vi.fn(),
  deleteEvent: vi.fn(),
  listEnrollments: vi.fn(),
  /**
   * isAdminApiError: mirrors the real implementation so useDocuments / useEvents
   * can distinguish success from error returns without importing the real module.
   */
  isAdminApiError: (x: unknown): boolean =>
    typeof x === "object" &&
    x !== null &&
    "ok" in x &&
    (x as { ok: boolean }).ok === false,
}))

// ── Imports of mocked modules and components ───────────────────────────────

import {
  listDocuments,
  replaceDocument,
  deleteDocument,
  listEvents,
} from "@/lib/adminApi"
import type { DocumentSummary } from "@/lib/adminApi"

import { AdminConsole } from "@/components/admin/AdminConsole"
import { DocumentList } from "@/components/admin/DocumentList"
import { DocumentCard } from "@/components/admin/DocumentCard"
import { StatusPill } from "@/components/admin/StatusPill"
import { DeleteConfirm } from "@/components/admin/DeleteConfirm"
import { Toaster } from "@/components/admin/Toaster"

// ── Fixtures ───────────────────────────────────────────────────────────────

const SESSION_KEY = "admin_token"
const TEST_TOKEN = "test-admin-token"

const pendingDoc: DocumentSummary = { id: 1, name: "intro.pdf", status: "pending" }
const readyDoc: DocumentSummary = { id: 3, name: "republic.pdf", status: "ready" }
const failedDoc: DocumentSummary = { id: 4, name: "notes.txt", status: "failed" }

// ── Setup / teardown ───────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.removeItem(SESSION_KEY)

  // Default: empty list and successful mutations so non-polling tests stay clean
  vi.mocked(listDocuments).mockResolvedValue([])
  vi.mocked(replaceDocument).mockResolvedValue({ id: 100 })
  vi.mocked(deleteDocument).mockResolvedValue(true)
  // Events hook is also active in AdminConsole; default to empty list so
  // existing document tests don't fail on missing events mock. req events-006.
  vi.mocked(listEvents).mockResolvedValue([])
})

afterEach(() => {
  // Always restore real timers so fake-timer state does not bleed between tests
  vi.useRealTimers()
})

// ── Helpers ────────────────────────────────────────────────────────────────

/** Seed the admin token into sessionStorage so AdminConsole shows the console. */
function seedToken() {
  sessionStorage.setItem(SESSION_KEY, TEST_TOKEN)
}

// ─────────────────────────────────────────────────────────────────────────────
// 012 — Polling while any doc is in-flight; stops when all docs are settled
// eval: admin-console-012
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-012 — polling: grows while in-flight, plateaus when settled", () => {
  it(
    "calls listDocuments repeatedly while a doc is pending, stops once all are ready/failed",
    async () => {
      // eval: admin-console-012
      vi.useFakeTimers()
      seedToken()

      // Phase 1: every call returns a pending document — polling must continue
      vi.mocked(listDocuments).mockResolvedValue([pendingDoc])

      render(<AdminConsole />)

      // Advance past the initial setTimeout(…, 0) that triggers the first refresh.
      // act(async) flushes the resolved-promise microtask queue so React processes
      // the setDocs([pendingDoc]) state update before we inspect call counts.
      await act(async () => {
        vi.advanceTimersByTime(1)
        await Promise.resolve() // flush mockResolvedValue microtasks
      })

      const afterInit = vi.mocked(listDocuments).mock.calls.length
      expect(afterInit).toBeGreaterThanOrEqual(1)

      // Advance one poll cycle (2 500 ms) — the setInterval callback fires
      await act(async () => {
        vi.advanceTimersByTime(2_500)
        await Promise.resolve()
      })

      const afterPoll1 = vi.mocked(listDocuments).mock.calls.length
      // Call count must have grown → polling is active
      expect(afterPoll1).toBeGreaterThan(afterInit)

      // Phase 2: all docs settle (ready) — one more tick, then polling must stop
      vi.mocked(listDocuments).mockResolvedValue([readyDoc])

      await act(async () => {
        vi.advanceTimersByTime(2_500)
        await Promise.resolve()
      })

      const countAfterSettle = vi.mocked(listDocuments).mock.calls.length

      // Advance a substantial additional window — no new calls expected
      await act(async () => {
        vi.advanceTimersByTime(20_000)
        await Promise.resolve()
      })

      // Call count plateaued — polling stopped
      expect(vi.mocked(listDocuments).mock.calls.length).toBe(countAfterSettle)
    },
  )
})

// ─────────────────────────────────────────────────────────────────────────────
// 013 — Manual refresh control re-fetches the list
// eval: admin-console-013
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-013 — manual Refresh control re-fetches the list", () => {
  it("calls onRefresh when the Refresh button is clicked", async () => {
    // eval: admin-console-013
    const onRefresh = vi.fn()
    const user = userEvent.setup()

    render(
      <DocumentList
        docs={[readyDoc]}
        isLoading={false}
        listError={null}
        onRefresh={onRefresh}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    const refreshBtn = screen.getByRole("button", { name: /refresh/i })
    await user.click(refreshBtn)

    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it("Refresh button is disabled while isLoading is true (prevents concurrent fetches)", () => {
    // eval: admin-console-013
    render(
      <DocumentList
        docs={[]}
        isLoading={true}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    const refreshBtn = screen.getByRole("button", { name: /refresh/i })
    expect(refreshBtn).toBeDisabled()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 014 — Empty state invites the first upload when there are no documents
// eval: admin-console-014
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-014 — empty state invites first upload", () => {
  it("renders the empty-state prose when docs is empty, not loading, and no error", () => {
    // eval: admin-console-014
    render(
      <DocumentList
        docs={[]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    // Headline inviting the admin to upload — exact text avoids matching the sr-only
    // status region which also contains "No documents yet" as part of a longer phrase.
    expect(screen.getByText("No documents yet.")).toBeInTheDocument()
    // Instructional copy referencing the upload action
    expect(screen.getByText(/Upload a PDF/i)).toBeInTheDocument()
  })

  it("does NOT show the empty state while loading", () => {
    // eval: admin-console-014
    render(
      <DocumentList
        docs={[]}
        isLoading={true}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    expect(screen.queryByText(/No documents yet/i)).toBeNull()
  })

  it("does NOT show the empty state when a listError is present", () => {
    // eval: admin-console-014
    render(
      <DocumentList
        docs={[]}
        isLoading={false}
        listError="Network error — please try again."
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    expect(screen.queryByText(/No documents yet/i)).toBeNull()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 015 — `failed` status: calm rendering, no alarm, no reason text exposed
// eval: admin-console-015
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-015 — failed status: calm pill, no alarm, no error detail", () => {
  it("StatusPill with status=failed shows 'Failed' label without an alarm role or red classes", () => {
    // eval: admin-console-015
    const { container } = render(<StatusPill status="failed" />)

    // The plain "Failed" label is visible
    expect(screen.getByText("Failed")).toBeInTheDocument()

    // No alarm roles — the pill must never be an alert banner
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(container.querySelector('[role="banner"]')).toBeNull()

    // No saturated-red Tailwind classes (text-red-*, bg-red-*, border-red-*)
    const html = container.innerHTML
    expect(html).not.toMatch(/text-red-\d|bg-red-\d|border-red-\d/)
    expect(html).not.toMatch(/text-alarm|bg-alarm|alert-red|alarm/)
  })

  it("failed DocumentCard does not expose any internal error reason or stack trace", () => {
    // eval: admin-console-015
    render(
      <DocumentCard
        doc={failedDoc}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    // "Failed" pill label is present
    expect(screen.getByText("Failed")).toBeInTheDocument()

    // Internal error details are never exposed
    expect(screen.queryByText(/error:/i)).toBeNull()
    expect(screen.queryByText(/reason:/i)).toBeNull()
    expect(screen.queryByText(/exception/i)).toBeNull()
    expect(screen.queryByText(/traceback/i)).toBeNull()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 016 — Replace on a card calls replaceDocument (PUT) with a valid file
// eval: admin-console-016
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-016 — Replace calls replaceDocument (PUT) with a valid file", () => {
  it("file selected via DocumentCard Replace calls onReplace with the valid file", async () => {
    // eval: admin-console-016
    // Test the DocumentCard presentational layer — onReplace spy
    const onReplace = vi.fn()
    const user = userEvent.setup()

    const { container } = render(
      <DocumentCard
        doc={readyDoc}
        onReplace={onReplace}
        onDelete={vi.fn()}
      />,
    )

    const fileInput = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement
    expect(fileInput).not.toBeNull()

    const replacementFile = new File(["updated content"], "updated.pdf", {
      type: "application/pdf",
    })

    // userEvent.upload dispatches the change event on the file input directly.
    // The element is aria-hidden (so it's off the a11y tree) but user-event can
    // still target it by direct DOM reference.
    await user.upload(fileInput, replacementFile)

    // onReplace is called with the valid file — extension .pdf passes validation
    expect(onReplace).toHaveBeenCalledTimes(1)
    expect(onReplace).toHaveBeenCalledWith(replacementFile)
  })

  it("full flow: Replace via AdminConsole calls replaceDocument with the token and file", async () => {
    // eval: admin-console-016 (integration)
    seedToken()
    vi.mocked(listDocuments).mockResolvedValue([readyDoc])

    const { container } = render(<AdminConsole />)

    // Wait for the doc card to appear after the initial list load
    await waitFor(() =>
      expect(screen.getByText(readyDoc.name)).toBeInTheDocument(),
    )

    // AdminConsole renders TWO hidden file inputs: the UploadDropzone's (first)
    // and the DocumentCard's Replace input (last). Target the card's input — the
    // first one would trigger the UPLOAD flow, not replace.
    const fileInputs = container.querySelectorAll('input[type="file"]')
    const fileInput = fileInputs[fileInputs.length - 1] as HTMLInputElement
    expect(fileInput).not.toBeNull()

    const replacementFile = new File(["updated"], "updated.pdf", {
      type: "application/pdf",
    })

    // The file input has aria-hidden="true" which can prevent userEvent.upload from
    // dispatching events in a deep component tree. Use Object.defineProperty +
    // fireEvent.change instead — this targets the DOM directly, bypassing the
    // accessibility tree check while still exercising the full component handler chain.
    Object.defineProperty(fileInput, "files", {
      value: [replacementFile],
      configurable: true,
      writable: true,
    })
    fireEvent.change(fileInput)

    // replaceDocument called with the correct token, doc id, and file
    await waitFor(
      () =>
        expect(replaceDocument).toHaveBeenCalledWith(
          TEST_TOKEN,
          readyDoc.id,
          replacementFile,
        ),
      { timeout: 3000 },
    )
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 017 — Delete requires explicit confirmation; confirmed delete issues DELETE
// eval: admin-console-017
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-017 — Delete requires confirmation; confirmed delete calls deleteDocument", () => {
  it("DeleteConfirm dialog shows the document name and calls onConfirm when Delete is clicked", async () => {
    // eval: admin-console-017
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const user = userEvent.setup()

    render(
      <DeleteConfirm
        open={true}
        doc={failedDoc}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    // Dialog is visible and names the target document
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(screen.getByText(failedDoc.name)).toBeInTheDocument()

    // Click the Delete action in the dialog
    const deleteBtn = within(screen.getByRole("dialog")).getByRole("button", {
      name: /^delete$/i,
    })
    await user.click(deleteBtn)

    expect(onConfirm).toHaveBeenCalledTimes(1)
    // onCancel must NOT fire on confirm
    expect(onCancel).not.toHaveBeenCalled()
  })

  it("full flow: clicking Delete card → confirm dialog → confirm → calls deleteDocument", async () => {
    // eval: admin-console-017 (integration)
    seedToken()
    vi.mocked(listDocuments).mockResolvedValue([readyDoc])

    const user = userEvent.setup()
    render(<AdminConsole />)

    // Wait for the doc card
    await waitFor(() =>
      expect(screen.getByText(readyDoc.name)).toBeInTheDocument(),
    )

    // Click Delete on the DocumentCard
    const cardDeleteBtn = within(
      screen.getByRole("article", { name: /Document: republic\.pdf/i }),
    ).getByRole("button", { name: /^delete$/i })
    await user.click(cardDeleteBtn)

    // Confirmation dialog must appear before any API call
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())
    expect(deleteDocument).not.toHaveBeenCalled()

    // Confirm deletion inside the dialog
    const dialogDeleteBtn = within(screen.getByRole("dialog")).getByRole(
      "button",
      { name: /^delete$/i },
    )
    await user.click(dialogDeleteBtn)

    // deleteDocument is called with the right token + id
    await waitFor(() =>
      expect(deleteDocument).toHaveBeenCalledWith(TEST_TOKEN, readyDoc.id),
    )
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 018 — Cancelling delete confirmation keeps the doc and sends no DELETE
// eval: admin-console-018
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-018 — cancel delete keeps doc; no DELETE request sent", () => {
  it("clicking Cancel in DeleteConfirm calls onCancel and NOT onConfirm", async () => {
    // eval: admin-console-018
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const user = userEvent.setup()

    render(
      <DeleteConfirm
        open={true}
        doc={readyDoc}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    const cancelBtn = screen.getByRole("button", { name: /cancel/i })
    await user.click(cancelBtn)

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("pressing Escape calls onCancel and does NOT fire onConfirm or the API", async () => {
    // eval: admin-console-018
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const user = userEvent.setup()

    render(
      <DeleteConfirm
        open={true}
        doc={readyDoc}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    // Cancel button receives autoFocus; pressing Escape from within the dialog
    // triggers the Dialog's onOpenChange(false) → onCancel path.
    await user.keyboard("{Escape}")

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
    // Critically: the network is never called
    expect(deleteDocument).not.toHaveBeenCalled()
  })

  it("full flow: cancelling the dialog keeps the document in the list (no DELETE)", async () => {
    // eval: admin-console-018 (integration)
    seedToken()
    vi.mocked(listDocuments).mockResolvedValue([readyDoc])

    const user = userEvent.setup()
    render(<AdminConsole />)

    await waitFor(() =>
      expect(screen.getByText(readyDoc.name)).toBeInTheDocument(),
    )

    // Open the delete dialog
    await user.click(
      within(
        screen.getByRole("article", { name: /Document: republic\.pdf/i }),
      ).getByRole("button", { name: /^delete$/i }),
    )

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())

    // Cancel
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /cancel/i }),
    )

    // No DELETE request was sent
    expect(deleteDocument).not.toHaveBeenCalled()

    // The document is still present
    expect(screen.getByText(readyDoc.name)).toBeInTheDocument()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 019 — Keyboard operable: correct roles, labels, and tab-reachability
// eval: admin-console-019
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-019 — keyboard operable controls with roles and accessible names", () => {
  it("Refresh button has an aria-label and is not disabled by default", () => {
    // eval: admin-console-019
    render(
      <DocumentList
        docs={[readyDoc]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    const refreshBtn = screen.getByRole("button", { name: /refresh/i })
    expect(refreshBtn).toBeInTheDocument()
    expect(refreshBtn).toHaveAttribute("aria-label")
    expect(refreshBtn).not.toBeDisabled()
  })

  it("Replace and Delete buttons in DocumentCard are standard focusable buttons", () => {
    // eval: admin-console-019
    render(
      <DocumentCard
        doc={readyDoc}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    const replaceBtn = screen.getByRole("button", { name: /replace/i })
    const deleteBtn = screen.getByRole("button", { name: /^delete$/i })

    expect(replaceBtn).toBeInTheDocument()
    expect(deleteBtn).toBeInTheDocument()
    // Both enabled when not busy
    expect(replaceBtn).not.toBeDisabled()
    expect(deleteBtn).not.toBeDisabled()
  })

  it("Replace and Delete are disabled (aria-disabled) when card is busy", () => {
    // eval: admin-console-019
    render(
      <DocumentCard
        doc={readyDoc}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busy={true}
      />,
    )

    const replaceBtn = screen.getByRole("button", { name: /replace/i })
    const deleteBtn = screen.getByRole("button", { name: /^delete$/i })

    expect(replaceBtn).toBeDisabled()
    expect(deleteBtn).toBeDisabled()
    expect(replaceBtn).toHaveAttribute("aria-disabled", "true")
    expect(deleteBtn).toHaveAttribute("aria-disabled", "true")
  })

  it("upload dropzone has role=button and tabIndex=0 for keyboard activation", async () => {
    // eval: admin-console-019
    seedToken()
    render(<AdminConsole />)

    // The dropzone is a <div role="button" tabIndex={0}> — keyboard-activatable
    const dropzone = screen.getByRole("button", {
      name: /upload a document/i,
    })
    expect(dropzone).toBeInTheDocument()
    expect(dropzone).toHaveAttribute("tabindex", "0")
  })

  it("Sign-out control is a button with identifiable English label", () => {
    // eval: admin-console-019
    seedToken()
    render(<AdminConsole />)

    const signOutBtn = screen.getByRole("button", { name: /sign out/i })
    expect(signOutBtn).toBeInTheDocument()
  })

  it("DeleteConfirm dialog buttons are keyboard-accessible (standard button roles)", () => {
    // eval: admin-console-019
    render(
      <DeleteConfirm
        open={true}
        doc={readyDoc}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    // Both dialog action buttons are real <button> elements (not divs)
    const cancelBtn = screen.getByRole("button", { name: /cancel/i })
    const deleteBtn = screen.getByRole("button", { name: /^delete$/i })

    expect(cancelBtn).toBeInTheDocument()
    expect(cancelBtn.tagName).toBe("BUTTON")
    expect(deleteBtn).toBeInTheDocument()
    expect(deleteBtn.tagName).toBe("BUTTON")
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 020 — aria-live regions announce status changes and toast messages
// eval: admin-console-020
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-020 — aria-live regions announce status and toast changes", () => {
  it("Toaster renders an aria-live=polite role=log region labelled Notifications", () => {
    // eval: admin-console-020
    render(<Toaster />)

    const liveRegion = screen.getByRole("log")
    expect(liveRegion).toBeInTheDocument()
    expect(liveRegion).toHaveAttribute("aria-live", "polite")
    // Individual toast items are announced separately (not the whole container at once)
    expect(liveRegion).toHaveAttribute("aria-atomic", "false")
    expect(liveRegion).toHaveAttribute("aria-label", "Notifications")
  })

  it("DocumentList has a sr-only role=status aria-live=polite region", () => {
    // eval: admin-console-020
    // NOTE: StatusPill also carries role="status" (per ARIA spec for status pill
    // elements). When docs are rendered, there will be multiple role="status"
    // elements on the page. We find the list-level announcer by its aria-atomic
    // attribute (the sr-only region uses aria-atomic="true"; StatusPill does not).
    render(
      <DocumentList
        docs={[readyDoc]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    const allStatusRegions = screen.getAllByRole("status")
    // The sr-only list announcer carries aria-atomic="true" and aria-live="polite"
    const announcer = allStatusRegions.find(
      (el) => el.getAttribute("aria-atomic") === "true",
    )
    expect(announcer).toBeDefined()
    expect(announcer).toHaveAttribute("aria-live", "polite")
    // Contains the count announcement so screen readers know the list updated
    expect(announcer).toHaveTextContent(/Document list refreshed/i)
  })

  it("status region announces 'Loading' while isLoading is true", () => {
    // eval: admin-console-020
    // Empty docs → no StatusPill rendered → safe single getByRole("status")
    render(
      <DocumentList
        docs={[]}
        isLoading={true}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    const statusRegion = screen.getByRole("status")
    expect(statusRegion).toHaveTextContent(/Loading/i)
  })

  it("status region announces empty list when docs is empty and idle", () => {
    // eval: admin-console-020
    // Empty docs → no StatusPill rendered → safe single getByRole("status")
    render(
      <DocumentList
        docs={[]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    const statusRegion = screen.getByRole("status")
    expect(statusRegion).toHaveTextContent(/No documents yet/i)
  })

  it("AdminConsole mounts the Toaster (aria-live log) alongside the console surface", async () => {
    // eval: admin-console-020
    seedToken()
    render(<AdminConsole />)

    // The Toaster's aria-live log is always in the DOM (registered before the
    // first toast fires, per the design spec).
    const log = screen.getByRole("log")
    expect(log).toBeInTheDocument()
    expect(log).toHaveAttribute("aria-live", "polite")
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 021 — Design-system tokens in use; classical aesthetic; WCAG AA documented
// eval: admin-console-021
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-021 — design tokens in use; classical aesthetic; WCAG AA", () => {
  it("StatusPill classes reference design tokens (not raw hex literals)", () => {
    // eval: admin-console-021
    // Each state uses Tailwind utilities that map to CSS custom properties defined
    // in globals.css — never raw hex values in class attribute strings.
    const states = ["pending", "ingesting", "ready", "failed"] as const

    for (const status of states) {
      const { container, unmount } = render(<StatusPill status={status} />)
      const html = container.innerHTML

      // No raw hex literals in the class attribute strings
      expect(html).not.toMatch(/class="[^"]*#[0-9a-fA-F]{3,8}/)

      unmount()
    }
  })

  it("StatusPill 'ready' uses bg-primary token; 'failed' uses bg-destructive token", () => {
    // eval: admin-console-021
    const { container: cReady } = render(<StatusPill status="ready" />)
    const { container: cFailed } = render(<StatusPill status="failed" />)

    // Token-based utilities — not raw hex
    expect(cReady.innerHTML).toMatch(/bg-primary/)
    expect(cFailed.innerHTML).toMatch(/bg-destructive/)
  })

  it("globals.css documents WCAG AA contrast ratios for the ink and aubergine tokens", () => {
    // eval: admin-console-021
    // Static assertion: the token comment header in globals.css must record the
    // WCAG AA claim so the contrast ratio is auditable alongside the token value.
    const css = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8")

    expect(css).toMatch(/WCAG AA/)
    expect(css).toContain("aubergine")
    // Ink token documented in the palette header
    expect(css).toMatch(/#1A1714|1A1714/)
    // Aubergine accent documented in the palette header
    expect(css).toMatch(/#6E2C50|6E2C50/)
  })

  it("DocumentList heading uses font-serif (Newsreader display face)", () => {
    // eval: admin-console-021
    render(
      <DocumentList
        docs={[]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    const heading = screen.getByRole("heading", { name: /documents/i })
    // font-serif maps to --font-serif (Newsreader) via the globals token
    expect(heading).toHaveClass("font-serif")
  })

  it("DeleteConfirm title uses font-heading (serif display face)", () => {
    // eval: admin-console-021
    render(
      <DeleteConfirm
        open={true}
        doc={readyDoc}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    // The dialog title is a serif heading per the design token system
    const title = screen.getByRole("heading")
    expect(title).toHaveClass("font-heading")
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 022 — All console copy is in English
// eval: admin-console-022
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-022 — console copy is in English", () => {
  it("DocumentList renders English heading and control labels", () => {
    // eval: admin-console-022
    render(
      <DocumentList
        docs={[readyDoc]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    expect(screen.getByRole("heading", { name: /documents/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument()
  })

  it("empty state copy is English", () => {
    // eval: admin-console-022
    render(
      <DocumentList
        docs={[]}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        busyId={null}
      />,
    )

    // Exact text (with period) avoids ambiguous match with the sr-only status region
    // which also contains "No documents yet" in a longer announcement string.
    expect(screen.getByText("No documents yet.")).toBeInTheDocument()
    expect(screen.getByText(/Upload a PDF/i)).toBeInTheDocument()
  })

  it("StatusPill labels are English for all four ingestion states", () => {
    // eval: admin-console-022
    const { rerender } = render(<StatusPill status="pending" />)
    expect(screen.getByText("Pending")).toBeInTheDocument()

    rerender(<StatusPill status="ingesting" />)
    expect(screen.getByText("Ingesting")).toBeInTheDocument()

    rerender(<StatusPill status="ready" />)
    expect(screen.getByText("Ready")).toBeInTheDocument()

    rerender(<StatusPill status="failed" />)
    expect(screen.getByText("Failed")).toBeInTheDocument()
  })

  it("DeleteConfirm copy is English: title fragment, description, and button labels", () => {
    // eval: admin-console-022
    render(
      <DeleteConfirm
        open={true}
        doc={readyDoc}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    // English description explaining the destructive consequence
    expect(
      screen.getByText(/This removes the document and all its indexed chunks/i),
    ).toBeInTheDocument()
    // English action labels
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /^delete$/i })).toBeInTheDocument()
  })

  it("DocumentCard action buttons carry English labels (Replace, Delete)", () => {
    // eval: admin-console-022
    render(
      <DocumentCard
        doc={readyDoc}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    expect(screen.getByRole("button", { name: /replace/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /^delete$/i })).toBeInTheDocument()
  })

  it("UploadDropzone prompt copy is English", () => {
    // eval: admin-console-022
    seedToken()
    render(<AdminConsole />)

    // The dropzone's idle prompt uses English copy
    expect(screen.getByText(/Drag a document here/i)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /upload a document/i }),
    ).toBeInTheDocument()
  })

  it("Sign-out control label is English", () => {
    // eval: admin-console-022
    seedToken()
    render(<AdminConsole />)

    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument()
  })
})
