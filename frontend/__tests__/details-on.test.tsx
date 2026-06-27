/**
 * __tests__/details-on.test.tsx
 *
 * Tests for frontend-shell-012 — the DetailsDisclosure component when the
 * NEXT_PUBLIC_SHOW_DETAILS flag is ON.
 *
 * This file lives separately from shell.test.tsx because each Vitest test file
 * has its own module registry.  Here @/lib/flags is mocked with
 * detailsDisclosure: true, whereas shell.test.tsx mocks it as false (default off).
 *
 * Traces: frontend-shell-012
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Module mock (hoisted) ────────────────────────────────────────────────────
// Must be declared before the component import so vitest's hoisting injects the
// mock before the module is resolved.

vi.mock("@/lib/flags", () => ({
  detailsDisclosure: true,
}));

// ── Component imports (receive the mocked flags) ─────────────────────────────

import { DetailsDisclosure } from "@/components/chat/contract/DetailsDisclosure";
import type { TurnOutput } from "@/lib/contract";

// ── Fixture ──────────────────────────────────────────────────────────────────

const contractWithDetails: TurnOutput = {
  reply: "The unexamined life is not worth living.",
  detected_lang: "en",
  active_lang: "en",
  lang_confidence: 0.88,
  final_normalized_text: "Tell me about Socrates",
  detected_country: "GB",
  confidence_score: 0.75,
  needs_review: false,
  guardrails: { input: [], output: [] },
};

// ─────────────────────────────────────────────────────────────────────────────
// 012 — details_disclosure flag ON → collapsible exposes 4 debug fields
// eval: frontend-shell-012
// ─────────────────────────────────────────────────────────────────────────────

describe("frontend-shell-012 — details flag ON: collapsible exposes 4 debug fields", () => {
  it("renders a keyboard-operable toggle button that reveals all 4 debug fields", async () => {
    // eval: frontend-shell-012
    const user = userEvent.setup();
    render(<DetailsDisclosure contract={contractWithDetails} lang="en" />);

    // The toggle button must exist (keyboard-operable)
    const toggle = screen.getByRole("button", { name: /details/i });
    expect(toggle).toBeInTheDocument();

    // Open the collapsible — base-ui Collapsible Panel shows its content on click
    await user.click(toggle);

    // All four debug fields must now be visible
    // 1. lang_confidence
    expect(
      screen.getByText(/Language confidence/i)
    ).toBeInTheDocument();
    // 2. confidence_score
    expect(
      screen.getByText(/Confidence score/i)
    ).toBeInTheDocument();
    // 3. detected_country
    expect(
      screen.getByText(/Detected country/i)
    ).toBeInTheDocument();
    // 4. final_normalized_text
    expect(
      screen.getByText(/Normalized text/i)
    ).toBeInTheDocument();

    // Verify actual values are rendered
    expect(screen.getByText("0.880")).toBeInTheDocument(); // lang_confidence.toFixed(3)
    expect(screen.getByText("0.750")).toBeInTheDocument(); // confidence_score.toFixed(3)
    expect(screen.getByText("GB")).toBeInTheDocument();   // detected_country
    expect(
      screen.getByText("Tell me about Socrates")
    ).toBeInTheDocument(); // final_normalized_text
  });

  it("toggle button is keyboard-accessible (Tab to focus, Enter to open)", async () => {
    // eval: frontend-shell-012 (keyboard operability)
    const user = userEvent.setup();
    render(<DetailsDisclosure contract={contractWithDetails} lang="en" />);

    const toggle = screen.getByRole("button", { name: /details/i });

    // Tab to the button and activate with Enter
    await user.tab();
    expect(toggle).toHaveFocus();

    await user.keyboard("{Enter}");

    // Content is now open
    expect(screen.getByText(/Language confidence/i)).toBeInTheDocument();
  });
});
