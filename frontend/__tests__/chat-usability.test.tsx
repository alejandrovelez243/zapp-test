/**
 * __tests__/chat-usability.test.tsx
 *
 * Usability-focused component tests for the chat surface enhancements:
 *   usability-001 — Empty state: welcome text + clickable starter prompts
 *   usability-002 — Thinking indicator in-transcript while status='sending'
 *   usability-003 — Send button: icon present + visible hint text
 *
 * Module-level mocks mirror those in shell.test.tsx so both suites can run
 * together without interference.
 *
 * Traces: usability-001, usability-002, usability-003
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TurnOutput } from "@/lib/contract";

// ── Module mocks (hoisted) ─────────────────────────────────────────────────

vi.mock("@/lib/api", async (importActual) => {
  const mod = await importActual<typeof import("@/lib/api")>();
  return { ...mod, postTurn: vi.fn() };
});

vi.mock("@/lib/session", () => ({
  getSessionId: vi.fn().mockReturnValue("sess-test-123"),
}));

vi.mock("@/lib/flags", () => ({
  detailsDisclosure: false,
}));

// ── Imports ────────────────────────────────────────────────────────────────

import { postTurn } from "@/lib/api";
import { getSessionId } from "@/lib/session";

import { ChatShell } from "@/components/chat/ChatShell";
import { EmptyState } from "@/components/chat/EmptyState";
import { ThinkingTurn } from "@/components/chat/ThinkingTurn";
import { Composer } from "@/components/chat/Composer";

// ── Shared fixtures ────────────────────────────────────────────────────────

const baseTurnOutput: TurnOutput = {
  reply: "Philosophy begins in wonder.",
  detected_lang: "en",
  active_lang: "en",
  lang_confidence: 0.97,
  final_normalized_text: "What is philosophy?",
  detected_country: "US",
  confidence_score: 0.92,
  needs_review: false,
  guardrails: { input: [], output: [] },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(postTurn).mockResolvedValue(baseTurnOutput);
  vi.mocked(getSessionId).mockReturnValue("sess-test-123");
});

// ─────────────────────────────────────────────────────────────────────────────
// usability-001a — Empty state renders welcome + prompts when turns=[]
// ─────────────────────────────────────────────────────────────────────────────

describe("usability-001 — empty state: welcome message and starter prompts", () => {
  it("shows the welcome text when no turns exist", () => {
    // eval: usability-001
    render(<ChatShell />);

    // The welcome sentence is visible in the empty state
    expect(
      screen.getByText(/Welcome\. The examined life begins/i)
    ).toBeInTheDocument();
  });

  it("renders all four starter-prompt buttons in the empty state", () => {
    // eval: usability-001
    render(<ChatShell />);

    // All four prompts are keyboard-operable buttons
    expect(
      screen.getByRole("button", { name: /What courses do you offer/i })
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /How do I enroll in an event/i })
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /What is Stoicism/i })
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /Tell me about the school/i })
    ).toBeInTheDocument();
  });

  it("clicking a starter prompt calls postTurn with the prompt text", async () => {
    // eval: usability-001
    const user = userEvent.setup();
    render(<ChatShell />);

    const promptBtn = screen.getByRole("button", {
      name: /What courses do you offer/i,
    });
    await user.click(promptBtn);

    await waitFor(() =>
      expect(postTurn).toHaveBeenCalledWith(
        "sess-test-123",
        "What courses do you offer?"
      )
    );
  });

  it("replaces the empty state with the transcript after a prompt is clicked", async () => {
    // eval: usability-001
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(
      screen.getByRole("button", { name: /How do I enroll/i })
    );

    // Once a student turn is appended, the EmptyState is gone and the
    // student message appears in the transcript
    await waitFor(() =>
      expect(
        screen.getByText(/How do I enroll in an event/i)
      ).toBeInTheDocument()
    );

    // Welcome text is no longer visible
    expect(
      screen.queryByText(/Welcome\. The examined life begins/i)
    ).toBeNull();
  });

  it("EmptyState prompts are keyboard-focusable and activate via Enter", async () => {
    // eval: usability-001 (keyboard operability)
    const onPrompt = vi.fn();
    const user = userEvent.setup();
    render(<EmptyState activeLang="en" onPrompt={onPrompt} />);

    // Tab to first prompt, then activate with Enter
    await user.tab();
    const focused = document.activeElement;
    expect(focused?.tagName).toBe("BUTTON");
    await user.keyboard("{Enter}");

    expect(onPrompt).toHaveBeenCalledOnce();
  });

  it("EmptyState localizes welcome and prompts to Spanish (es)", () => {
    // eval: usability-001 + frontend-shell-014
    render(<EmptyState activeLang="es" onPrompt={vi.fn()} />);

    expect(
      screen.getByText(/Bienvenido\. La vida examinada/i)
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /¿Qué cursos ofrecéis/i })
    ).toBeInTheDocument();
  });

  it("EmptyState localizes welcome and prompts to Portuguese (pt)", () => {
    // eval: usability-001 + frontend-shell-014
    render(<EmptyState activeLang="pt" onPrompt={vi.fn()} />);

    expect(
      screen.getByText(/Bem-vindo\. A vida examinada/i)
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /Que cursos oferecem/i })
    ).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// usability-002 — Thinking indicator visible in-transcript while sending
// ─────────────────────────────────────────────────────────────────────────────

describe("usability-002 — thinking indicator visible while status=sending", () => {
  it("shows the ThinkingTurn in transcript while a request is in flight", async () => {
    // eval: usability-002
    let resolvePost!: (v: TurnOutput) => void;
    const controlled = new Promise<TurnOutput>((r) => {
      resolvePost = r;
    });
    vi.mocked(postTurn).mockReturnValueOnce(controlled);

    const user = userEvent.setup();
    render(<ChatShell />);

    await user.type(screen.getByRole("textbox"), "What is virtue?");
    await user.keyboard("{Enter}");

    // While in flight, the ThinkingTurn element is present
    await waitFor(() =>
      expect(
        screen.getByTestId("thinking-turn")
      ).toBeInTheDocument()
    );

    // Resolve to clean up
    await act(async () => {
      resolvePost(baseTurnOutput);
    });

    // After resolution, thinking turn disappears
    await waitFor(() =>
      expect(screen.queryByTestId("thinking-turn")).toBeNull()
    );
  });

  it("ThinkingTurn has role=status for screen-reader announcement", () => {
    // eval: usability-002 (accessibility)
    render(<ThinkingTurn activeLang="en" />);

    const el = screen.getByRole("status");
    expect(el).toBeInTheDocument();
    // The element contains the localized thinking label
    expect(el).toHaveTextContent(/Thinking/i);
  });

  it("ThinkingTurn localizes label to Spanish", () => {
    // eval: usability-002 + frontend-shell-014
    render(<ThinkingTurn activeLang="es" />);
    expect(screen.getByRole("status")).toHaveTextContent(/Pensando/i);
  });

  it("ThinkingTurn does not appear when status=idle after a resolved turn", async () => {
    // eval: usability-002
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.type(screen.getByRole("textbox"), "Hello");
    await user.keyboard("{Enter}");

    // Wait for the full round-trip to complete (reply arrives, status=idle)
    await waitFor(() =>
      expect(screen.getByText("Philosophy begins in wonder.")).toBeInTheDocument()
    );

    // No thinking indicator remains
    expect(screen.queryByTestId("thinking-turn")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// usability-003 — Send button has icon; hint text is present and localized
// ─────────────────────────────────────────────────────────────────────────────

describe("usability-003 — clearer send affordance: icon + localized hint", () => {
  it("Send button renders an svg icon alongside the label", () => {
    // eval: usability-003
    render(<Composer onSend={vi.fn()} status="idle" activeLang="en" />);

    const button = screen.getByRole("button", { name: /send/i });
    // An <svg> element is present inside the button (the lucide icon)
    const svg = button.querySelector("svg");
    expect(svg).not.toBeNull();
    // Icon is aria-hidden so it does not double-announce to screen readers
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("hint text 'Enter to send' is visible below the composer in English", () => {
    // eval: usability-003
    render(<Composer onSend={vi.fn()} status="idle" activeLang="en" />);
    expect(
      screen.getByText(/Enter to send/i)
    ).toBeInTheDocument();
  });

  it("hint text is localized for Spanish", () => {
    // eval: usability-003 + frontend-shell-014
    render(<Composer onSend={vi.fn()} status="idle" activeLang="es" />);
    expect(
      screen.getByText(/Intro para enviar/i)
    ).toBeInTheDocument();
  });

  it("hint text is localized for Portuguese", () => {
    // eval: usability-003 + frontend-shell-014
    render(<Composer onSend={vi.fn()} status="idle" activeLang="pt" />);
    expect(
      screen.getByText(/Enter para enviar/i)
    ).toBeInTheDocument();
  });

  it("icon is not rendered while status=sending (button shows pending label only)", () => {
    // eval: usability-003 + frontend-shell-005
    render(<Composer onSend={vi.fn()} status="sending" activeLang="en" />);

    const button = screen.getByRole("button", { name: /send/i });
    // While sending the button shows the pending label — no SVG icon
    const svg = button.querySelector("svg");
    expect(svg).toBeNull();
  });
});
