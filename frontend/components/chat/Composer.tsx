"use client";

/**
 * components/chat/Composer.tsx
 *
 * The message-input surface. Presentational: it receives `onSend`, `status`,
 * and `activeLang` as props. The `useChat` hook is wired upstream in ChatShell
 * (task 11) — this component never calls it directly.
 *
 * Keyboard contract (req frontend-shell-007):
 *   Enter (no Shift)   → submit trimmed non-empty message and clear textarea
 *   Shift+Enter        → browser default (inserts newline in textarea)
 *   IME composition    → suppress Enter-to-submit while mid-composition
 *
 * Pending contract (req frontend-shell-005):
 *   While status==='sending': textarea + button are disabled; submission is
 *   blocked in both the keydown handler and the click handler.
 *
 * Accessibility (req frontend-shell-020):
 *   - Explicit <label> paired to the textarea via htmlFor / id.
 *   - Visible focus ring rendered by the shadcn textarea/button theme tokens
 *     (focus-visible:border-ring focus-visible:ring-ring/50).
 *   - Button has an aria-label that mirrors its visible text.
 *   - Hint text is in a <p> that updates calmly; aria-live="polite" ensures
 *     the "Thinking…" state is announced to screen readers without alarm.
 *
 * Traces: frontend-shell-005, frontend-shell-007, frontend-shell-020
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { t } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ComposerProps {
  /** Called with the trimmed message when the student submits. */
  onSend: (msg: string) => void;
  /**
   * 'idle'    — ready to accept input.
   * 'sending' — a request is in flight; textarea + button are disabled and a
   *             pending affordance is shown (req frontend-shell-005).
   */
  status: "idle" | "sending";
  /**
   * ISO 639-1 code from the per-turn contract `active_lang` field (or the
   * session default before the first turn).  Drives all chrome copy via `t()`.
   */
  activeLang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Composer — textarea + send button that forms the bottom of the chat surface.
 *
 * Intentionally small: no internal API calls, no session logic, no contract
 * consumption.  The parent (ChatShell) drives all state changes via props.
 */
export function Composer({ onSend, status, activeLang }: ComposerProps) {
  const [value, setValue] = React.useState("");
  /**
   * IME composition guard (req frontend-shell-007).
   *
   * On mobile / CJK keyboards the browser fires compositionstart before the
   * user has finished composing a character.  If we submit on Enter during that
   * window we send a partial / raw phoneme.  We track composition state with a
   * ref (not state, to avoid re-renders) and ignore Enter-to-submit while
   * `isComposing.current === true`.
   *
   * NOTE: In modern Chrome (v53+) compositionend fires BEFORE the trailing
   * keydown, so the ref is already false by the time handleKeyDown runs.
   * Older browsers invert this order, making the ref guard essential for
   * correct cross-browser behaviour.
   */
  const isComposing = React.useRef(false);

  const isSending = status === "sending";
  const composerId = React.useId();

  // ── Derived copy ─────────────────────────────────────────────────────────

  const placeholder = t(activeLang, "composer.placeholder");
  const sendLabel = t(activeLang, "composer.sendLabel");
  const hintText = isSending
    ? t(activeLang, "state.sending")
    : t(activeLang, "composer.hint");

  // ── Submission ────────────────────────────────────────────────────────────

  /** Core submit: validates, calls onSend, resets. */
  function submit() {
    // Req frontend-shell-005: block second submit while in flight.
    if (isSending) return;
    const trimmed = value.trim();
    // Do not send empty messages.
    if (!trimmed) return;
    onSend(trimmed);
    setValue("");
  }

  // ── Event handlers ────────────────────────────────────────────────────────

  /**
   * handleKeyDown — req frontend-shell-007.
   *
   * Enter (no Shift, not composing) → submit.
   * Shift+Enter → let the browser insert a newline (no preventDefault).
   * Any other key (including Enter-while-composing) → pass through.
   */
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      // IME guard: don't submit while mid-composition.
      if (isComposing.current) return;
      e.preventDefault();
      submit();
    }
    // Shift+Enter: default textarea behaviour inserts a newline — do nothing.
  }

  function handleCompositionStart() {
    isComposing.current = true;
  }

  function handleCompositionEnd() {
    isComposing.current = false;
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-2 w-full">
      {/*
        Label is visually hidden but available to screen readers; the
        placeholder provides a visual cue for sighted users.
        req frontend-shell-020: every interactive element is keyboard operable
        and labelled.
      */}
      <label htmlFor={composerId} className="sr-only">
        {placeholder}
      </label>

      <div className="flex items-end gap-2">
        <Textarea
          id={composerId}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          placeholder={placeholder}
          disabled={isSending}
          /*
           * Req frontend-shell-020: visible focus indicator — the shadcn
           * Textarea already applies `focus-visible:ring-3 focus-visible:ring-ring/50`
           * which maps to the theme --ring (aubergine accent) token.
           */
          className="resize-none flex-1 min-h-[3rem] max-h-48"
          rows={1}
        />

        {/*
          Req frontend-shell-020: button is keyboard-operable and has an
          accessible aria-label.
          Disabled when sending (req 005) or when there is no non-empty text to
          send (good UX, also guards the empty-string case defensively).
        */}
        <Button
          type="button"
          onClick={submit}
          disabled={isSending || !value.trim()}
          aria-label={sendLabel}
          size="lg"
          className="shrink-0 self-end"
        >
          {/*
            Show localized 'Send' normally; while sending, show the pending
            label so the button itself communicates the in-flight state.
            req frontend-shell-005: calm pending affordance.
          */}
          {isSending ? t(activeLang, "state.sending") : sendLabel}
        </Button>
      </div>

      {/*
        Hint text beneath the composer: shows keyboard shortcut copy normally,
        or "Thinking…" (state.sending) while a request is in flight.
        aria-live="polite" lets a screen reader announce the change without
        interrupting ongoing speech — req frontend-shell-020.
      */}
      <p
        className="text-xs text-muted-foreground pl-0.5 select-none"
        aria-live="polite"
        aria-atomic="true"
      >
        {hintText}
      </p>
    </div>
  );
}
