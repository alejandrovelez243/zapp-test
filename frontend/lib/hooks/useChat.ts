"use client";

/**
 * lib/hooks/useChat.ts
 *
 * State machine for the anonymous chat surface.
 *
 * Transitions: idle → sending → (rendered | error) → idle
 *
 * Guarantees:
 *   - Student turn is appended to the transcript immediately on submit.
 *   - Concurrent submits are blocked while a request is in flight.
 *   - On success, the assistant turn (full contract attached) is appended.
 *   - On any failure, a localized error turn is appended; prior turns are
 *     never dropped.
 *   - `status` returns to "idle" unconditionally (try/finally).
 *   - Exposes `activeLang` — the ISO 639-1 code from the most recent
 *     successful assistant turn — so chrome components can mirror it
 *     (supports task 11 / req frontend-shell-015).
 *
 * Traces:
 *   frontend-shell-003 — append student turn + POST with session_id
 *   frontend-shell-005 — pending state + concurrent submit guard
 *   frontend-shell-006 — failure/non-contract → localized error turn,
 *                         transcript preserved
 */

import { useCallback, useRef, useState } from "react";
import type { ChatTurn } from "../contract";
import { isApiError, postTurn } from "../api";
import { getSessionId } from "../session";
import { t, type I18nKey } from "../i18n";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** The two observable states of the send-request lifecycle. */
export type ChatStatus = "idle" | "sending";

/** Shape returned by useChat — consumed by ChatShell and its children. */
export interface UseChatReturn {
  /** Ordered transcript of all turns in this session (never shrinks). */
  turns: ChatTurn[];
  /** Current lifecycle state; "sending" while a request is in flight. */
  status: ChatStatus;
  /**
   * ISO 639-1 code from the most recent successful assistant contract
   * (`active_lang`).  Defaults to "en" before any reply has arrived.
   * Chrome components read this to localize labels (req frontend-shell-015).
   */
  activeLang: string;
  /**
   * Submit a student message.
   *
   * No-ops if `status === "sending"` (concurrent-submit guard, req 005)
   * or if `message` is blank / whitespace-only.
   *
   * Sequence on a non-guarded call:
   *   1. Append `{ role: "student", text: message }` to the transcript (req 003).
   *   2. Set `status = "sending"` (req 005).
   *   3. POST to the backend via `postTurn(session_id, message)` (req 003).
   *   4a. On `TurnOutput`: append `{ role: "assistant", ... }`, update `activeLang`.
   *   4b. On `ApiError`:   append `{ role: "error", text: <localized> }` (req 006).
   *   5. Restore `status = "idle"` unconditionally.
   */
  send: (message: string) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Chat state machine hook.
 *
 * Pure hook — no DOM access, no side-effects beyond React state updates.
 * Must be called from a "use client" component (e.g. ChatShell).
 */
export function useChat(): UseChatReturn {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [activeLang, setActiveLang] = useState<string>("en");

  /**
   * Ref-based guard so `send` is a stable callback reference (empty dep array)
   * and the concurrent-submit check is always current regardless of closures.
   * React 18 batches setState, so a boolean ref is the reliable way to lock
   * without depending on the rendered `status` value inside the closure.
   */
  const sendingRef = useRef<boolean>(false);

  /**
   * Ref mirrors the latest `activeLang` state so the async error handler can
   * read it without a stale closure (the closure captures the ref object, not
   * the state value, so it always sees the current language).
   */
  const activeLangRef = useRef<string>("en");

  const send = useCallback(async (message: string): Promise<void> => {
    // Req frontend-shell-005: block concurrent submission and blank messages.
    if (sendingRef.current || message.trim() === "") return;

    // Acquire the in-flight lock before any await.
    sendingRef.current = true;

    // Req frontend-shell-003: append the student turn immediately so the UI
    // reflects the message before waiting for the network.
    setTurns((prev) => [...prev, { role: "student", text: message }]);

    // Req frontend-shell-005: signal pending state to disable the composer.
    setStatus("sending");

    try {
      // Req frontend-shell-003: POST with the stable session_id.
      const result = await postTurn(getSessionId(), message);

      if (!isApiError(result)) {
        // Successful per-turn contract: append assistant turn with the full
        // contract so ContractMeta components can read every field (req 004).
        const assistantTurn: ChatTurn = {
          role: "assistant",
          text: result.reply,
          contract: result,
        };
        setTurns((prev) => [...prev, assistantTurn]);

        // Update the language mirror so subsequent chrome and error messages
        // use the session's latest locked language (req frontend-shell-015).
        activeLangRef.current = result.active_lang;
        setActiveLang(result.active_lang);
      } else {
        // Req frontend-shell-006: any API failure → localized error turn.
        // Choose the most specific key: network vs other (http / malformed).
        const errorKey: I18nKey =
          result.kind === "network" ? "error.network" : "error.generic";
        const errorText = t(activeLangRef.current, errorKey);

        // Append error turn; prior turns are preserved (functional update).
        setTurns((prev) => [...prev, { role: "error", text: errorText }]);
      }
    } finally {
      // Req frontend-shell-005: always restore idle so the composer re-enables.
      setStatus("idle");
      sendingRef.current = false;
    }
  }, []); // stable — guards use refs, state updates are safe via functional form

  return { turns, status, send, activeLang };
}
