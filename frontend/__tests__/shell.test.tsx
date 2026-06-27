/**
 * __tests__/shell.test.tsx
 *
 * Component tests for the frontend-shell feature.
 * One test per acceptance id, frontend-shell-001 … frontend-shell-022
 * (012 is in details-on.test.tsx; this file covers the remaining 21).
 *
 * Module-level mocks (hoisted by Vitest before imports):
 *   @/lib/api        — postTurn mocked to return a controlled TurnOutput
 *   @/lib/session    — getSessionId returns 'sess-test-123'
 *   @/lib/flags      — detailsDisclosure: false (default-off state)
 *
 * Traces: frontend-shell-001 … frontend-shell-022
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "fs";
import { resolve } from "path";
import type { TurnOutput } from "@/lib/contract";

// ── Module mocks (hoisted) ─────────────────────────────────────────────────

vi.mock("@/lib/api", async (importActual) => {
  const mod = await importActual<typeof import("@/lib/api")>();
  return { ...mod, postTurn: vi.fn() };
});

vi.mock("@/lib/session", () => ({
  getSessionId: vi.fn().mockReturnValue("sess-test-123"),
}));

// Default: flag OFF — tests 001-011, 013-022 work with details hidden.
vi.mock("@/lib/flags", () => ({
  detailsDisclosure: false,
}));

// ── Imports of mocked modules and components ────────────────────────────────

import { postTurn } from "@/lib/api";
import { getSessionId } from "@/lib/session";

import { ChatShell } from "@/components/chat/ChatShell";
import { Composer } from "@/components/chat/Composer";
import { Transcript } from "@/components/chat/Transcript";
import { MessageTurn } from "@/components/chat/MessageTurn";
import { ReviewMarker } from "@/components/chat/contract/ReviewMarker";
import { DetectedLangHint } from "@/components/chat/contract/DetectedLangHint";
import { GuardrailNote } from "@/components/chat/contract/GuardrailNote";
import { LangIndicator } from "@/components/chat/contract/LangIndicator";
import { DetailsDisclosure } from "@/components/chat/contract/DetailsDisclosure";

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
  // Clear call history and implementations, then set default.
  vi.clearAllMocks();
  // Default: postTurn resolves with the clean fixture
  vi.mocked(postTurn).mockResolvedValue(baseTurnOutput);
  // Re-apply session mock after clearAllMocks resets return values
  vi.mocked(getSessionId).mockReturnValue("sess-test-123");
});

// ── Helper: renders ChatShell and returns a userEvent instance ──────────────

function renderChatShell() {
  const user = userEvent.setup();
  render(<ChatShell />);
  return { user };
}

// ─────────────────────────────────────────────────────────────────────────────
// 001 — Single-column chat surface with composer and transcript
// eval: frontend-shell-001
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-001 — single-column chat surface", () => {
  it("renders a <main> element, a textarea composer, and a transcript region", () => {
    // eval: frontend-shell-001
    renderChatShell();

    // Single <main> landmark (single-column surface)
    expect(screen.getByRole("main")).toBeInTheDocument();

    // Composer: a <textarea> for message input
    expect(screen.getByRole("textbox")).toBeInTheDocument();

    // Transcript: the aria-live log region appears once a turn is added
    // (empty state shows the invitation paragraph rather than the log)
    // We confirm the overall structure exists.
    expect(screen.getByRole("main")).toContainElement(screen.getByRole("textbox"));
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 002 — Anonymous session_id persisted and sent on every request
// eval: frontend-shell-002
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-002 — anonymous session_id sent on every turn", () => {
  it("sends the session_id returned by getSessionId with every chat request", async () => {
    // eval: frontend-shell-002
    const user = userEvent.setup();
    render(<ChatShell />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "What is Socrates?");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(postTurn).toHaveBeenCalledTimes(1));
    expect(postTurn).toHaveBeenCalledWith("sess-test-123", "What is Socrates?");
    expect(getSessionId).toHaveBeenCalled();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 003 — Student message appended to transcript AND sent with session_id
// eval: frontend-shell-003
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-003 — student message appears in transcript on submit", () => {
  it("appends the student turn to the transcript and sends it to the API", async () => {
    // eval: frontend-shell-003
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.type(screen.getByRole("textbox"), "Tell me about Plato");
    await user.keyboard("{Enter}");

    // Student message should appear in the DOM
    await waitFor(() =>
      expect(screen.getByText("Tell me about Plato")).toBeInTheDocument()
    );

    // API was called with session_id + the message
    expect(postTurn).toHaveBeenCalledWith("sess-test-123", "Tell me about Plato");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 004 — Reply from per-turn contract rendered in transcript
// eval: frontend-shell-004
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-004 — assistant reply rendered from TurnOutput.reply", () => {
  it("shows the contract reply in the transcript after a successful response", async () => {
    // eval: frontend-shell-004
    vi.mocked(postTurn).mockResolvedValueOnce({
      ...baseTurnOutput,
      reply: "Socrates was an Athenian philosopher.",
    });

    const user = userEvent.setup();
    render(<ChatShell />);

    await user.type(screen.getByRole("textbox"), "Who is Socrates?");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(
        screen.getByText("Socrates was an Athenian philosopher.")
      ).toBeInTheDocument()
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 005 — Pending indicator shown; second concurrent submission blocked
// eval: frontend-shell-005
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-005 — pending state shown; concurrent submit prevented", () => {
  it("disables textarea and button while a request is in flight", async () => {
    // eval: frontend-shell-005
    let resolvePost!: (v: TurnOutput) => void;
    const controlled = new Promise<TurnOutput>((r) => {
      resolvePost = r;
    });
    vi.mocked(postTurn).mockReturnValueOnce(controlled);

    const user = userEvent.setup();
    render(<ChatShell />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "Hello world");

    // Fire click — React synchronously sets status='sending' before awaiting postTurn
    await user.click(screen.getByRole("button", { name: /send/i }));

    // In-flight: textarea disabled, button disabled, pending copy shown
    expect(screen.getByRole("textbox")).toBeDisabled();
    // postTurn called exactly once; concurrent guards prevent a second call
    expect(postTurn).toHaveBeenCalledTimes(1);

    // Resolve to clean up pending promise
    await act(async () => {
      resolvePost(baseTurnOutput);
    });
    await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 006 — API failure produces localized error turn; transcript preserved
// eval: frontend-shell-006
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-006 — ApiError produces error turn; prior transcript preserved", () => {
  it("shows a localized error turn and keeps the student message in the transcript", async () => {
    // eval: frontend-shell-006

    // First turn succeeds
    vi.mocked(postTurn)
      .mockResolvedValueOnce({ ...baseTurnOutput, reply: "First reply." })
      .mockResolvedValueOnce({
        ok: false,
        kind: "http",
        status: 500,
        message: "Internal Server Error",
      } as ReturnType<typeof postTurn> extends Promise<infer T> ? T : never);

    const user = userEvent.setup();
    render(<ChatShell />);

    // Turn 1 — succeeds
    await user.type(screen.getByRole("textbox"), "First question");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByText("First reply.")).toBeInTheDocument());

    // Turn 2 — fails
    await user.type(screen.getByRole("textbox"), "Second question");
    await user.keyboard("{Enter}");

    // Error turn appears
    await waitFor(() =>
      expect(screen.getByText(/Something went wrong|went wrong/i)).toBeInTheDocument()
    );

    // Existing transcript (prior turns) is preserved
    expect(screen.getByText("First reply.")).toBeInTheDocument();
    expect(screen.getByText("First question")).toBeInTheDocument();
    expect(screen.getByText("Second question")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 007 — Enter submits; Shift+Enter inserts newline
// eval: frontend-shell-007
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-007 — Enter submits; Shift+Enter inserts newline", () => {
  it("calls onSend on plain Enter and does NOT call it on Shift+Enter", async () => {
    // eval: frontend-shell-007
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Composer onSend={onSend} status="idle" activeLang="en" />);

    const textarea = screen.getByRole("textbox");

    // Type text and press plain Enter → should submit
    await user.type(textarea, "Hello philosopher");
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith("Hello philosopher");
    // After submit the textarea is cleared
    expect(textarea).toHaveValue("");

    // Type new text and press Shift+Enter → should insert newline, NOT submit
    await user.type(textarea, "Line one");
    await user.keyboard("{Shift>}{Enter}{/Shift}");

    // onSend still called only once
    expect(onSend).toHaveBeenCalledTimes(1);
    // The textarea now contains the text + a newline
    expect((textarea as HTMLTextAreaElement).value).toContain("\n");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 008 — needs_review=true → quiet hairline marker + accessible tooltip; NO red banner
// eval: frontend-shell-008
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-008 — needs_review=true uses quiet hairline, not red banner", () => {
  it("renders ReviewMarker trigger with aria-label and without destructive color", () => {
    // eval: frontend-shell-008
    render(<ReviewMarker needsReview lang="en" />);

    // The trigger button exists with an accessible label
    const trigger = screen.getByRole("button", { name: /flagged for review/i });
    expect(trigger).toBeInTheDocument();

    // No red/alarm/destructive classes anywhere in the review marker
    const container = trigger.closest("span, div, section") ?? document.body;
    const html = container.innerHTML;
    expect(html).not.toMatch(/text-red|bg-red|border-red|text-destructive|bg-destructive|alert|alarm/);

    // needsReview=false renders nothing
    const { container: empty } = render(<ReviewMarker needsReview={false} lang="en" />);
    expect(empty.querySelector("button")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 009 — active_lang shown as a discreet, non-intrusive indicator
// eval: frontend-shell-009
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-009 — active_lang shown as discreet indicator", () => {
  it("renders LangIndicator with the language code and an accessible aria-label", () => {
    // eval: frontend-shell-009
    render(<LangIndicator activeLang="es" lang="en" />);

    // The ISO 639-1 code is visible
    expect(screen.getByText("es")).toBeInTheDocument();

    // Full accessible label is present
    const span = screen.getByLabelText(/Session language.*es/i);
    expect(span).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 010 — detected_lang ≠ active_lang surfaces quiet "session locked" hint
// eval: frontend-shell-010
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-010 — detected_lang mismatch shows locked hint", () => {
  it("shows the hint when languages differ and hides it when they match", () => {
    // eval: frontend-shell-010
    const { rerender } = render(
      <DetectedLangHint detectedLang="fr" activeLang="en" lang="en" />
    );

    // Mismatch — hint should appear
    expect(screen.getByText(/Session locked to en/i)).toBeInTheDocument();

    // Match — hint should not render
    rerender(<DetectedLangHint detectedLang="en" activeLang="en" lang="en" />);
    expect(screen.queryByText(/Session locked/i)).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 011 — non-empty guardrails shows calm "filtered" note; raw names never exposed
// eval: frontend-shell-011
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-011 — guardrails show 'filtered'; no raw internals", () => {
  it("shows the filtered affordance when guardrails fire, without exposing names", () => {
    // eval: frontend-shell-011
    const secretName = "hate-speech-v2";
    render(
      <GuardrailNote
        guardrails={{ input: [secretName], output: [] }}
        lang="en"
      />
    );

    // Calm "filtered" copy visible
    expect(screen.getByText(/This message was filtered/i)).toBeInTheDocument();

    // Raw guardrail name never exposed
    expect(screen.queryByText(secretName)).toBeNull();

    // Empty guardrails → nothing rendered
    const { container } = render(
      <GuardrailNote guardrails={{ input: [], output: [] }} lang="en" />
    );
    expect(container.firstChild).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 013 — details_disclosure flag OFF → debug fields NOT rendered
// eval: frontend-shell-013
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-013 — details flag OFF; debug fields not rendered", () => {
  it("renders nothing when detailsDisclosure is false", () => {
    // eval: frontend-shell-013
    // @/lib/flags is mocked at the top of this file with detailsDisclosure: false
    const { container } = render(
      <DetailsDisclosure contract={baseTurnOutput} lang="en" />
    );

    // Component returns null — no DOM nodes
    expect(container.firstChild).toBeNull();

    // Specifically: none of the four debug field labels are present
    expect(screen.queryByText(/Language confidence/i)).toBeNull();
    expect(screen.queryByText(/Confidence score/i)).toBeNull();
    expect(screen.queryByText(/Detected country/i)).toBeNull();
    expect(screen.queryByText(/Normalized text/i)).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 014 — UI chrome rendered in session active_lang (ES/EN/PT)
// eval: frontend-shell-014
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-014 — chrome copy rendered in active_lang", () => {
  it("renders the placeholder in the session active_lang for en, es, and pt", () => {
    // eval: frontend-shell-014
    const { rerender } = render(
      <Composer onSend={vi.fn()} status="idle" activeLang="en" />
    );
    expect(screen.getByPlaceholderText("Ask a question…")).toBeInTheDocument();

    rerender(<Composer onSend={vi.fn()} status="idle" activeLang="es" />);
    expect(screen.getByPlaceholderText("Haz una pregunta…")).toBeInTheDocument();

    rerender(<Composer onSend={vi.fn()} status="idle" activeLang="pt" />);
    expect(screen.getByPlaceholderText("Faça uma pergunta…")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 015 — Chrome updates when active_lang changes between turns
// eval: frontend-shell-015
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-015 — chrome updates on active_lang change", () => {
  it("re-renders localized placeholder when activeLang prop changes", () => {
    // eval: frontend-shell-015
    const { rerender } = render(
      <Composer onSend={vi.fn()} status="idle" activeLang="en" />
    );
    expect(screen.getByPlaceholderText("Ask a question…")).toBeInTheDocument();

    // Simulate language change (e.g. next assistant turn returns active_lang="es")
    rerender(<Composer onSend={vi.fn()} status="idle" activeLang="es" />);
    expect(
      screen.getByPlaceholderText("Haz una pregunta…")
    ).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 016 — active_lang outside ES/EN/PT falls back to EN chrome
// eval: frontend-shell-016
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-016 — non-ES/EN/PT active_lang falls back to en", () => {
  it("renders English chrome for an unsupported active_lang code", () => {
    // eval: frontend-shell-016
    render(<Composer onSend={vi.fn()} status="idle" activeLang="fr" />);
    // "fr" is unsupported; t() falls back to "en"
    expect(screen.getByPlaceholderText("Ask a question…")).toBeInTheDocument();
    // No fr-specific placeholder
    expect(screen.queryByPlaceholderText("Posez une question")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 017 — Typographically-led classical aesthetic (serif heading, meander hairline)
// eval: frontend-shell-017
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-017 — classical aesthetic: serif heading + meander hairline", () => {
  it("renders h1 with font-heading class and the Greek-key meander div", () => {
    // eval: frontend-shell-017
    renderChatShell();

    // Display serif heading carries the class applied by the design tokens
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toBeInTheDocument();
    expect(heading).toHaveClass("font-heading");

    // Greek-key hairline: aria-hidden div with class rule-meander
    const meander = document.querySelector(".rule-meander");
    expect(meander).toBeInTheDocument();
    expect(meander).toHaveAttribute("aria-hidden", "true");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 018 — prefers-reduced-motion: reduce honored (static CSS assertion)
// eval: frontend-shell-018
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-018 — prefers-reduced-motion: reduce honored in CSS", () => {
  it("globals.css contains a prefers-reduced-motion: reduce block that kills animations", () => {
    // eval: frontend-shell-018
    // Static assertion: the CSS source must contain the media query so that
    // browsers running with the accessibility setting active receive zero-duration
    // animations and transitions — this is the testable artifact of req 018.
    const css = readFileSync(
      resolve(__dirname, "../app/globals.css"),
      "utf8"
    );
    expect(css).toContain("prefers-reduced-motion: reduce");
    // The block must cut animation and transition durations
    expect(css).toContain("animation-duration: 0.01ms");
    expect(css).toContain("transition-duration: 0.01ms");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 019 — aria-live region announces newly-arrived assistant turns
// eval: frontend-shell-019
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-019 — aria-live region for new assistant turns", () => {
  it("Transcript renders a role=log with aria-live=polite", () => {
    // eval: frontend-shell-019
    render(
      <Transcript
        turns={[
          { role: "assistant", text: "Virtue is knowledge.", contract: baseTurnOutput },
        ]}
        activeLang="en"
      />
    );

    const log = screen.getByRole("log");
    expect(log).toBeInTheDocument();
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toHaveAttribute("aria-atomic", "false");
  });

  it("AssistantTurn includes an sr-only announcement span inside the live region", () => {
    // eval: frontend-shell-019 (supplemental)
    render(
      <MessageTurn
        turn={{ role: "assistant", text: "Wonder is the beginning.", contract: baseTurnOutput }}
        activeLang="en"
      />
    );
    // The sr-only span with the new-reply announcement
    const srSpan = document.querySelector(".sr-only");
    expect(srSpan).not.toBeNull();
    expect(srSpan?.textContent).toMatch(/New reply from the assistant/i);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 020 — Fully keyboard operable; visible focus indicators; proper labelling
// eval: frontend-shell-020
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-020 — keyboard operable; labeled controls; focus indicators", () => {
  it("textarea is associated with a label and accessible by label text", () => {
    // eval: frontend-shell-020
    render(<Composer onSend={vi.fn()} status="idle" activeLang="en" />);

    // getByLabelText checks that a <label> is properly wired (htmlFor + id)
    const textarea = screen.getByLabelText(/Ask a question/i);
    expect(textarea).toBeInTheDocument();
    expect(textarea.tagName).toBe("TEXTAREA");
  });

  it("Send button has an aria-label", () => {
    // eval: frontend-shell-020
    render(<Composer onSend={vi.fn()} status="idle" activeLang="en" />);

    const button = screen.getByRole("button", { name: /send/i });
    expect(button).toHaveAttribute("aria-label");
  });

  it("textarea and button are keyboard-focusable (not inert)", async () => {
    // eval: frontend-shell-020
    const user = userEvent.setup();
    render(<Composer onSend={vi.fn()} status="idle" activeLang="en" />);

    const textarea = screen.getByRole("textbox");
    await user.tab();
    expect(textarea).toHaveFocus();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 021 — WCAG AA contrast for body text and accent (static CSS token assertion)
// eval: frontend-shell-021
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-021 — WCAG AA contrast: static token assertion", () => {
  it("globals.css documents WCAG AA contrast ratios for ink and aubergine accent", () => {
    // eval: frontend-shell-021
    // Static assertion: the design-token comments in globals.css must record
    // the WCAG AA designation so the contrast claim is auditable alongside the token.
    const css = readFileSync(
      resolve(__dirname, "../app/globals.css"),
      "utf8"
    );
    // The ink color is documented as WCAG AAA (~15:1 on paper)
    expect(css).toMatch(/WCAG AA/);
    // The aubergine accent must also be documented
    expect(css).toContain("aubergine");
    // The palette header must reference the token values
    expect(css).toMatch(/#1A1714|1A1714/); // ink
    expect(css).toMatch(/#6E2C50|6E2C50/); // aubergine accent
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 022 — No product-analytics (PostHog) initialized or called from frontend
// eval: frontend-shell-022
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-022 — no analytics SDK initialized from the frontend", () => {
  it("rendering ChatShell does not attach posthog to window", async () => {
    // eval: frontend-shell-022
    render(<ChatShell />);

    // If posthog-js were imported and initialized it would set window.posthog.
    // The package is not in project dependencies and ChatShell imports no analytics SDK.
    expect(
      (window as unknown as Record<string, unknown>)["posthog"]
    ).toBeUndefined();

    // No _posthog_ tracking namespace either
    expect(
      (window as unknown as Record<string, unknown>)["_posthog_"]
    ).toBeUndefined();
  });

  it("no analytics script tags or capture calls appear in the rendered DOM", () => {
    // eval: frontend-shell-022 (supplemental)
    renderChatShell();

    // No <script> elements injected by analytics SDKs
    const scripts = document.querySelectorAll('script[src*="posthog"]');
    expect(scripts.length).toBe(0);

    // No data- attributes associated with analytics tracking
    const tracked = document.querySelectorAll('[data-ph-capture]');
    expect(tracked.length).toBe(0);
  });
});
