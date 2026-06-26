"use client";

// Minimal chat page — scaffold for platform-scaffold-018.
// Full philosophical design (typography, palette, motion) is introduced in the
// frontend-shell spec. This page is intentionally bare: it proves the contract
// seam (POST /chat via NEXT_PUBLIC_API_URL -> render reply) and nothing more.

import { useState } from "react";

// Canonical per-turn contract fields rendered by this scaffold page.
// Full TurnOutput model is in backend/app/contract.py (platform-scaffold-011).
interface TurnOutput {
  reply: string;
  active_lang: string;
  detected_lang: string;
  needs_review: boolean;
  guardrails: { input: string[]; output: string[] };
}

interface Turn {
  role: "user" | "assistant";
  content: string;
  /** ISO 639-1 code the session is locked to — only set on assistant turns. */
  active_lang?: string;
  needs_review?: boolean;
}

// NEXT_PUBLIC_API_URL is build-time inlined by Next.js. It is NEVER a secret.
// Default: http://localhost:8000 for local dev without Docker Compose.
const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ChatPage() {
  // Stable anonymous session_id — persists for the lifetime of the browser tab.
  const [sessionId] = useState<string>(() => crypto.randomUUID());
  const [message, setMessage] = useState<string>("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    const trimmed = message.trim();
    if (!trimmed || loading) return;

    setTurns((prev) => [...prev, { role: "user", content: trimmed }]);
    setMessage("");
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: trimmed }),
      });

      if (!res.ok) {
        throw new Error(`Server responded ${res.status}`);
      }

      const data: TurnOutput = (await res.json()) as TurnOutput;

      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply,
          active_lang: data.active_lang,
          needs_review: data.needs_review,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline (accessibility requirement).
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <main style={css.main}>
      <h1 style={css.heading}>Philosophy School</h1>

      {/* aria-live announces assistant replies to screen readers */}
      <section
        aria-label="Conversation"
        aria-live="polite"
        aria-atomic="false"
        style={css.conversation}
      >
        {turns.map((turn, idx) => (
          <article
            key={idx}
            style={turn.role === "user" ? css.userTurn : css.assistantTurn}
          >
            {/* Role label + metadata chips on the same row */}
            <div style={css.turnMeta}>
              <span style={css.roleLabel}>
                {turn.role === "user" ? "You" : "Assistant"}
              </span>

              {/* active_lang badge: only on assistant turns, discreet monospaced label.
                  aria-label spells out the full description so screen readers are clear. */}
              {turn.role === "assistant" && turn.active_lang != null && (
                <span
                  style={css.langBadge}
                  title={`Session language: ${turn.active_lang.toUpperCase()}`}
                  aria-label={`Session language locked to ${turn.active_lang.toUpperCase()}`}
                >
                  {turn.active_lang.toUpperCase()}
                </span>
              )}

              {/* needs_review chip: visible text + tooltip — never a red banner.
                  Paired with text (not color alone) to meet WCAG AA non-color cue rule. */}
              {turn.needs_review === true && (
                <span
                  style={css.reviewChip}
                  title="This turn was flagged for review (low confidence or unsupported language)"
                  aria-label="Flagged for review"
                  role="note"
                >
                  needs review
                </span>
              )}
            </div>

            <p style={css.turnContent}>{turn.content}</p>
          </article>
        ))}

        {loading && (
          <p style={css.muted} aria-live="polite">
            Thinking…
          </p>
        )}

        {error !== null && (
          <p style={css.errorNote} role="alert">
            Error: {error}
          </p>
        )}
      </section>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        style={css.form}
      >
        {/* Visually hidden label satisfies WCAG AA labeling requirement */}
        <label htmlFor="chat-input" style={css.srOnly}>
          Your message
        </label>
        <textarea
          id="chat-input"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
          rows={3}
          style={css.textarea}
          disabled={loading}
          aria-describedby="chat-hint"
        />
        <span id="chat-hint" style={css.srOnly}>
          Press Enter to send, Shift+Enter to add a new line
        </span>
        <button
          type="submit"
          disabled={loading || message.trim() === ""}
          style={css.sendButton}
        >
          Send
        </button>
      </form>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Inline CSS-in-JS object — deliberately minimal at scaffold stage.
// The frontend-shell spec will replace this with Tailwind + shadcn primitives
// and the full typographic/palette design system.
// ---------------------------------------------------------------------------

const css: Record<string, React.CSSProperties> = {
  main: {
    maxWidth: "680px",
    margin: "0 auto",
    padding: "2rem 1rem",
    fontFamily: "Georgia, 'Times New Roman', serif",
    color: "#1a1a1a",
    lineHeight: 1.6,
  },
  heading: {
    fontSize: "1.5rem",
    fontWeight: 600,
    marginBottom: "1.5rem",
    letterSpacing: "-0.01em",
  },
  conversation: {
    minHeight: "200px",
    marginBottom: "1.5rem",
    display: "flex",
    flexDirection: "column",
    gap: "1.25rem",
  },
  userTurn: {
    textAlign: "right",
  },
  assistantTurn: {
    textAlign: "left",
  },
  // Row that holds the role label plus metadata chips (active_lang, needs_review).
  turnMeta: {
    display: "flex",
    alignItems: "center",
    gap: "0.4rem",
    marginBottom: "0.25rem",
  },
  roleLabel: {
    fontSize: "0.7rem",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: "#777",
  },
  turnContent: {
    margin: 0,
    whiteSpace: "pre-wrap",
  },
  // Discreet monospaced badge that mirrors the session's active_lang ("ES" / "EN" / "PT").
  // Muted border + low-contrast text keeps it informational without drawing the eye.
  langBadge: {
    fontSize: "0.6rem",
    fontFamily: "ui-monospace, 'Courier New', monospace",
    letterSpacing: "0.06em",
    color: "#999",
    border: "1px solid #ddd",
    borderRadius: "3px",
    padding: "0.05rem 0.3rem",
    lineHeight: 1,
    cursor: "default",
  },
  // Subtle "needs review" chip — not a red banner.
  // Text label + tooltip satisfies WCAG non-color cue requirement (text alone conveys meaning).
  reviewChip: {
    fontSize: "0.6rem",
    letterSpacing: "0.04em",
    color: "#999",
    border: "1px solid #e0ddd8",
    borderRadius: "3px",
    padding: "0.05rem 0.3rem",
    lineHeight: 1,
    cursor: "help",
    fontStyle: "italic",
  },
  muted: {
    color: "#888",
    fontStyle: "italic",
    fontSize: "0.9rem",
    margin: 0,
  },
  errorNote: {
    color: "#b00",
    fontSize: "0.875rem",
    margin: 0,
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "0.75rem",
  },
  // Screen-reader-only utility — satisfies WCAG AA labeling without visual clutter.
  srOnly: {
    position: "absolute",
    width: "1px",
    height: "1px",
    padding: 0,
    margin: "-1px",
    overflow: "hidden",
    clip: "rect(0,0,0,0)",
    whiteSpace: "nowrap",
    borderWidth: 0,
  },
  textarea: {
    width: "100%",
    padding: "0.75rem",
    fontSize: "1rem",
    fontFamily: "inherit",
    border: "1px solid #ccc",
    borderRadius: "4px",
    resize: "vertical",
    boxSizing: "border-box",
    lineHeight: 1.5,
  },
  sendButton: {
    alignSelf: "flex-end",
    padding: "0.5rem 1.5rem",
    fontSize: "0.9rem",
    cursor: "pointer",
    backgroundColor: "#1a1a1a",
    color: "#fff",
    border: "none",
    borderRadius: "4px",
    letterSpacing: "0.03em",
  },
};
