/**
 * components/chat/Transcript.tsx
 *
 * Single-column ordered list of conversation turns, wrapped in an aria-live
 * log region so assistive technology announces newly-appended turns.
 *
 * Presentational: receives `turns` and `activeLang` as props; no client-side
 * state or refs are required at this task scope (autoscroll refs belong to
 * ChatShell in task 11).
 *
 * The outer element carries `role="log"` (which implies `aria-live="polite"`
 * semantically) plus the explicit `aria-live` and `aria-atomic` attributes for
 * maximum assistive-technology compatibility.  When the parent appends a new
 * assistant turn to the `turns` array and React re-renders this component, the
 * browser's accessibility tree notifies the screen reader of the delta —
 * satisfying req frontend-shell-019 without any JavaScript polling or effect.
 *
 * Traces: frontend-shell-001, frontend-shell-004, frontend-shell-019
 */

import type { ChatTurn } from "@/lib/contract";
import { t } from "@/lib/i18n";
import { MessageTurn } from "./MessageTurn";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TranscriptProps {
  /**
   * Ordered sequence of all turns in the session.  The array grows
   * monotonically — turns are appended by the useChat hook and are never
   * removed or reordered.
   */
  turns: ChatTurn[];
  /**
   * ISO 639-1 code from the per-turn contract's `active_lang` field.
   * Drives the aria-label of the log region and any chrome copy inside
   * MessageTurn.  Defaults to "en" before the first assistant reply arrives.
   */
  activeLang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Transcript — renders the conversation as an aria-live log.
 *
 * `aria-atomic="false"` ensures that only newly-inserted DOM nodes are
 * announced, not the entire historical transcript, preventing the screen
 * reader from re-reading everything on every turn.
 */
export function Transcript({ turns, activeLang }: TranscriptProps) {
  return (
    <div
      role="log"
      aria-live="polite"
      aria-atomic="false"
      aria-label={t(activeLang, "a11y.transcriptLabel")}
      className="w-full"
    >
      {/*
       * <ol> is the semantically correct element: turns are ordered in time
       * and the sequence matters.  `list-none` suppresses visual markers;
       * vertical position alone conveys order, consistent with the editorial
       * aesthetic (req frontend-shell-017).
       */}
      <ol className="list-none p-0 m-0">
        {turns.map((turn, index) => (
          // Stable key: index is safe here because turns only ever grow
          // (never reordered or removed), so React's reconciler will not
          // confuse existing items.
          <li key={index} className="list-none">
            <MessageTurn turn={turn} activeLang={activeLang} />
          </li>
        ))}
      </ol>
    </div>
  );
}
