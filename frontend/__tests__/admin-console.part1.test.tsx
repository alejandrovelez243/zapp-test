/**
 * __tests__/admin-console.part1.test.tsx
 *
 * Component tests for admin-console feature — Part 1.
 * Covers acceptance ids admin-console-001 … admin-console-011 ONLY.
 * (012–022 are handled in a separate file.)
 *
 * Mocks:
 *   @/lib/adminApi             — listDocuments, uploadDocument, deleteDocument,
 *                                replaceDocument (vi.fn()); isAdminApiError kept real.
 *   @/components/admin/Toaster — useToast() returns a spy; Toaster renders null.
 *
 * Traces: admin-console-001 … admin-console-011
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

// ── Hoisted spy (used inside the vi.mock factory below) ───────────────────────
const mockAddToast = vi.hoisted(() => vi.fn())

// ── Module mocks (hoisted before all imports) ─────────────────────────────────

// Keep isAdminApiError and type shapes from the real module; replace I/O fns.
vi.mock("@/lib/adminApi", async (importActual) => {
  const mod = await importActual<typeof import("@/lib/adminApi")>()
  return {
    ...mod,
    listDocuments: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    replaceDocument: vi.fn(),
  }
})

// Toaster: useToast returns our spy so useDocuments picks it up; <Toaster />
// renders null (no live region needed for these 11 tests — we check the spy).
vi.mock("@/components/admin/Toaster", () => ({
  useToast: () => ({ addToast: mockAddToast }),
  Toaster: () => null,
}))

// ── Imports ────────────────────────────────────────────────────────────────────

import { listDocuments, uploadDocument } from "@/lib/adminApi"
import type { AdminApiError, DocumentSummary } from "@/lib/adminApi"

import { AdminConsole } from "@/components/admin/AdminConsole"
import { UploadDropzone } from "@/components/admin/UploadDropzone"
import { DocumentList } from "@/components/admin/DocumentList"
import { StatusPill } from "@/components/admin/StatusPill"

// ── Shared fixtures ────────────────────────────────────────────────────────────

const AUTH_ERROR: AdminApiError = {
  ok: false,
  kind: "auth",
  status: 401,
  message: "Unauthorized",
}

const NETWORK_ERROR: AdminApiError = {
  ok: false,
  kind: "network",
  message: "Network error — please try again.",
}

const FOUR_DOCS: DocumentSummary[] = [
  { id: 1, name: "intro.pdf", status: "ready" },
  { id: 2, name: "ethics.md", status: "pending" },
  { id: 3, name: "logic.txt", status: "failed" },
  { id: 4, name: "metaphysics.txt", status: "ingesting" },
]

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  // Safe defaults — callers override per-test as needed
  vi.mocked(listDocuments).mockResolvedValue([])
  vi.mocked(uploadDocument).mockResolvedValue({ id: 99 })
})

// ─────────────────────────────────────────────────────────────────────────────
// 001 — No stored token → gate shown; no adminApi call made
// eval: admin-console-001
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-001 — gate shown with no stored token; no API call", () => {
  it("renders TokenGate and no listDocuments call before the gate is passed", () => {
    // eval: admin-console-001
    // sessionStorage is clear (beforeEach). No token → gate view.
    render(<AdminConsole />)

    // Gate landmark shown (TokenGate renders <main aria-label="Admin access">)
    expect(
      screen.getByRole("main", { name: /Admin access/i })
    ).toBeInTheDocument()

    // Token entry form is present
    expect(screen.getByLabelText(/Admin token/i)).toBeInTheDocument()

    // Console-specific controls are NOT shown
    expect(
      screen.queryByRole("button", { name: /Sign out/i })
    ).toBeNull()
    expect(
      screen.queryByRole("button", { name: /Upload a document/i })
    ).toBeNull()

    // listDocuments NOT called synchronously.
    // The hook registers a setTimeout(0) which the effect cleanup cancels on
    // unmount — so the call never fires during this synchronous assertion window.
    expect(vi.mocked(listDocuments)).not.toHaveBeenCalled()
    expect(vi.mocked(uploadDocument)).not.toHaveBeenCalled()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 002 — Submitting a token persists it and listDocuments is called with it
// eval: admin-console-002
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-002 — token persisted to sessionStorage; sent via listDocuments", () => {
  it("stores the token and calls listDocuments with it after gate submission", async () => {
    // eval: admin-console-002
    const user = userEvent.setup()
    render(<AdminConsole />)

    await user.type(screen.getByLabelText(/Admin token/i), "test-admin-secret")
    await user.click(screen.getByRole("button", { name: /Continue/i }))

    // Token persisted to sessionStorage (req 002, 005)
    expect(sessionStorage.getItem("admin_token")).toBe("test-admin-secret")

    // listDocuments called with the submitted token (covers the X-Admin-Token path;
    // authHeaders() inside adminApi.ts maps token → "X-Admin-Token" header)
    await waitFor(() => {
      expect(vi.mocked(listDocuments)).toHaveBeenCalledWith("test-admin-secret")
    })
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 003 — 401/403 from any request → gate re-shown with "invalid/expired" message
// eval: admin-console-003
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-003 — 401/403 clears token and returns to gate with message", () => {
  it("shows the gate with an auth error when listDocuments returns 401", async () => {
    // eval: admin-console-003
    sessionStorage.setItem("admin_token", "expired-token")
    vi.mocked(listDocuments).mockResolvedValue(AUTH_ERROR)

    render(<AdminConsole />)

    // After the 401, AdminConsole clears the token and mounts TokenGate with error
    await waitFor(() => {
      expect(
        screen.getByRole("main", { name: /Admin access/i })
      ).toBeInTheDocument()
    })

    // Error message rendered as role="alert" (TokenGate's error prop)
    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent(/missing|invalid|expired/i)

    // Token cleared from sessionStorage
    expect(sessionStorage.getItem("admin_token")).toBeNull()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 004 — Sign-out control clears the token and returns to the gate
// eval: admin-console-004
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-004 — sign-out clears token and returns to gate", () => {
  it("removes the sessionStorage token and shows the gate after clicking Sign out", async () => {
    // eval: admin-console-004
    sessionStorage.setItem("admin_token", "valid-token")
    const user = userEvent.setup()

    render(<AdminConsole />)

    // Console view: Sign out button is immediately visible (token set synchronously)
    const signOutBtn = screen.getByRole("button", { name: /Sign out/i })
    expect(signOutBtn).toBeInTheDocument()

    await user.click(signOutBtn)

    // Token cleared
    expect(sessionStorage.getItem("admin_token")).toBeNull()

    // Gate is now shown
    expect(
      screen.getByRole("main", { name: /Admin access/i })
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/Admin token/i)).toBeInTheDocument()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 005 — Admin token never comes from NEXT_PUBLIC_* env var or page bundle
// eval: admin-console-005
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-005 — token sourced from gate input / sessionStorage only", () => {
  it("no NEXT_PUBLIC_* env var contains an admin token or secret", () => {
    // eval: admin-console-005
    // NEXT_PUBLIC_* vars are build-time inlined into the bundle — never secrets.
    // This assertion guards that no admin token is accidentally exposed this way.
    const publicKeys = Object.keys(process.env).filter((k) =>
      k.startsWith("NEXT_PUBLIC_")
    )
    const suspectKeys = publicKeys.filter((k) =>
      /token|admin|secret|auth/i.test(k)
    )
    expect(suspectKeys).toHaveLength(0)
    // Specifically the most likely offender
    expect(process.env.NEXT_PUBLIC_ADMIN_TOKEN).toBeUndefined()
  })

  it("token stored under literal sessionStorage key 'admin_token', not an env value", async () => {
    // eval: admin-console-005
    // Behavioral: the gate form collects the token at runtime and stores it
    // under a hard-coded key — never derived from a NEXT_PUBLIC_* variable.
    const user = userEvent.setup()
    render(<AdminConsole />)

    await user.type(screen.getByLabelText(/Admin token/i), "gate-supplied-token")
    await user.click(screen.getByRole("button", { name: /Continue/i }))

    // The literal key "admin_token" was used — confirms runtime provenance
    expect(sessionStorage.getItem("admin_token")).toBe("gate-supplied-token")
    // Not sourced from any env var
    expect(process.env.NEXT_PUBLIC_ADMIN_TOKEN).toBeUndefined()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 006 — UploadDropzone operable by click and keyboard (Enter / Space)
// eval: admin-console-006
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-006 — UploadDropzone operable by click and keyboard", () => {
  it("has role=button and tabIndex=0 (keyboard-reachable)", () => {
    // eval: admin-console-006
    render(<UploadDropzone onFile={vi.fn()} />)

    const zone = screen.getByRole("button", { name: /Upload a document/i })
    expect(zone).toBeInTheDocument()
    // tabIndex=0 means it is in the natural tab order
    expect(zone).toHaveAttribute("tabIndex", "0")
  })

  it("Enter key opens the file picker (invokes the hidden input click)", () => {
    // eval: admin-console-006
    const clickSpy = vi
      .spyOn(HTMLInputElement.prototype, "click")
      .mockImplementation(() => {})

    render(<UploadDropzone onFile={vi.fn()} />)
    const zone = screen.getByRole("button", { name: /Upload a document/i })

    fireEvent.keyDown(zone, { key: "Enter" })

    expect(clickSpy).toHaveBeenCalledTimes(1)
    clickSpy.mockRestore()
  })

  it("Space key also opens the file picker", () => {
    // eval: admin-console-006
    const clickSpy = vi
      .spyOn(HTMLInputElement.prototype, "click")
      .mockImplementation(() => {})

    render(<UploadDropzone onFile={vi.fn()} />)
    const zone = screen.getByRole("button", { name: /Upload a document/i })

    fireEvent.keyDown(zone, { key: " " })

    expect(clickSpy).toHaveBeenCalledTimes(1)
    clickSpy.mockRestore()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 007 — Non-PDF/MD/TXT file rejected with role="alert"; no upload request
// eval: admin-console-007
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-007 — invalid file type rejected inline; onFile NOT called", () => {
  it("shows a role=alert rejection for .docx and does NOT call onFile", () => {
    // eval: admin-console-007
    const onFile = vi.fn()
    render(<UploadDropzone onFile={onFile} />)

    const fileInput = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement

    const docxFile = new File(["content"], "notes.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    })

    fireEvent.change(fileInput, { target: { files: [docxFile] } })

    // Inline rejection message shown as role="alert" (req 007)
    const alert = screen.getByRole("alert")
    expect(alert).toBeInTheDocument()
    // Message names the offending extension or states "not accepted"
    expect(alert.textContent).toMatch(/\.docx|not accepted/i)

    // onFile (and therefore uploadDocument) NOT called before any request
    expect(onFile).not.toHaveBeenCalled()
  })

  it("shows rejection for .zip and does NOT call onFile", () => {
    // eval: admin-console-007 (supplemental — additional non-accepted type)
    const onFile = vi.fn()
    render(<UploadDropzone onFile={onFile} />)

    const fileInput = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement

    fireEvent.change(fileInput, {
      target: {
        files: [new File(["data"], "archive.zip", { type: "application/zip" })],
      },
    })

    expect(screen.getByRole("alert")).toBeInTheDocument()
    expect(onFile).not.toHaveBeenCalled()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 008 — Valid upload shows pending / in-progress feedback (busy=true)
// eval: admin-console-008
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-008 — in-progress feedback shown while upload is in flight", () => {
  it("renders Uploading copy and a busy aria-label when busy=true", () => {
    // eval: admin-console-008
    render(<UploadDropzone onFile={vi.fn()} busy={true} />)

    // BusyIndicator sub-component shows "Uploading…" copy
    expect(screen.getByText(/Uploading/i)).toBeInTheDocument()

    // The zone's aria-label communicates the busy state to assistive technology
    const zone = screen.getByRole("button")
    expect(zone).toHaveAttribute(
      "aria-label",
      expect.stringMatching(/Uploading|please wait/i)
    )
  })

  it("valid .pdf file triggers onFile (pre-condition: not busy)", () => {
    // eval: admin-console-008 (non-busy path: accepted file proceeds to onFile)
    const onFile = vi.fn()
    render(<UploadDropzone onFile={onFile} busy={false} />)

    const fileInput = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement
    const pdfFile = new File(["pdf"], "doc.pdf", { type: "application/pdf" })

    fireEvent.change(fileInput, { target: { files: [pdfFile] } })

    // Valid type → onFile called (no rejection)
    expect(onFile).toHaveBeenCalledWith(pdfFile)
    expect(screen.queryByRole("alert")).toBeNull()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 009 — Upload success → success toast AND document list refreshed
// eval: admin-console-009
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-009 — upload success shows success toast and refreshes list", () => {
  it("fires addToast(success, …) and calls listDocuments twice on upload success", async () => {
    // eval: admin-console-009
    sessionStorage.setItem("admin_token", "valid-token")
    vi.mocked(listDocuments).mockResolvedValue([])
    vi.mocked(uploadDocument).mockResolvedValue({ id: 42 })

    render(<AdminConsole />)

    // Wait for the initial list load to complete (deferred via setTimeout 0)
    await waitFor(() =>
      expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1)
    )

    // UploadDropzone is the first input[type="file"] in the DOM
    // (AdminConsole renders <UploadDropzone> before <DocumentList>)
    const fileInput = document.querySelectorAll(
      'input[type="file"]'
    )[0] as HTMLInputElement

    const pdfFile = new File(["pdf content"], "philosophy.pdf", {
      type: "application/pdf",
    })
    fireEvent.change(fileInput, { target: { files: [pdfFile] } })

    // Success toast fired (req 009)
    await waitFor(() => {
      expect(mockAddToast).toHaveBeenCalledWith(
        "success",
        expect.stringContaining("uploaded")
      )
    })

    // List refreshed — listDocuments called a second time after upload (req 009)
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(2)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 010 — Upload failure → calm error toast; existing list preserved
// eval: admin-console-010
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-010 — upload failure shows error toast; list not cleared", () => {
  it("fires addToast(error, …) and preserves the document list on upload failure", async () => {
    // eval: admin-console-010
    sessionStorage.setItem("admin_token", "valid-token")

    const existingDocs: DocumentSummary[] = [
      { id: 1, name: "existing-doc.pdf", status: "ready" },
    ]
    vi.mocked(listDocuments).mockResolvedValue(existingDocs)
    vi.mocked(uploadDocument).mockResolvedValue(NETWORK_ERROR)

    render(<AdminConsole />)

    // Wait for initial list load so existingDocs are rendered
    await waitFor(() =>
      expect(screen.getByText("existing-doc.pdf")).toBeInTheDocument()
    )

    // UploadDropzone's file input (first in DOM — before DocumentCard inputs)
    const fileInput = document.querySelectorAll(
      'input[type="file"]'
    )[0] as HTMLInputElement

    const txtFile = new File(["content"], "new-doc.txt", { type: "text/plain" })
    fireEvent.change(fileInput, { target: { files: [txtFile] } })

    // Calm error toast fired (req 010)
    await waitFor(() => {
      expect(mockAddToast).toHaveBeenCalledWith("error", expect.any(String))
    })

    // listDocuments NOT called a second time — no refresh on failure (req 010)
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1)

    // Existing document still displayed — list preserved (req 010)
    expect(screen.getByText("existing-doc.pdf")).toBeInTheDocument()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 011 — Documents rendered as cards / rows each with a StatusPill
// eval: admin-console-011
// ─────────────────────────────────────────────────────────────────────────────

describe("admin-console-011 — documents rendered as cards with StatusPill for each status", () => {
  it("renders a card per document, each showing its name and a StatusPill", () => {
    // eval: admin-console-011
    render(
      <DocumentList
        docs={FOUR_DOCS}
        isLoading={false}
        listError={null}
        onRefresh={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    // Each document name is present in the DOM
    expect(screen.getByText("intro.pdf")).toBeInTheDocument()
    expect(screen.getByText("ethics.md")).toBeInTheDocument()
    expect(screen.getByText("logic.txt")).toBeInTheDocument()
    expect(screen.getByText("metaphysics.txt")).toBeInTheDocument()

    // Each StatusPill is present, identified by its accessible name (aria-label).
    // role="status" elements without the matching name (e.g. DocumentList's sr-only
    // announcement div) are filtered out by the { name } option.
    expect(
      screen.getByRole("status", { name: /Status: ready/i })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("status", { name: /Status: pending/i })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("status", { name: /Status: failed/i })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("status", { name: /Status: ingesting/i })
    ).toBeInTheDocument()
  })

  it("StatusPill renders the correct label text for each of the four statuses", () => {
    // eval: admin-console-011 (supplemental — isolated StatusPill)
    const { rerender } = render(<StatusPill status="ready" />)
    expect(screen.getByText("Ready")).toBeInTheDocument()

    rerender(<StatusPill status="pending" />)
    expect(screen.getByText("Pending")).toBeInTheDocument()

    rerender(<StatusPill status="ingesting" />)
    expect(screen.getByText("Ingesting")).toBeInTheDocument()

    rerender(<StatusPill status="failed" />)
    expect(screen.getByText("Failed")).toBeInTheDocument()
  })
})
