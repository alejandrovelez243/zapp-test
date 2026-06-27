/**
 * components/chat/contract/GuardrailNote.tsx
 *
 * Calm "filtered" affordance for turns where guardrails fired (req
 * frontend-shell-011).
 *
 * Shows ONLY the localised "filtered" copy — never raw guardrail names,
 * category codes, counts, or any internal detail (req 011).
 *
 * Returns null (renders nothing) when both guardrails.input and
 * guardrails.output are empty arrays.
 *
 * Purely presentational: no client state, no browser APIs.
 *
 * Traces: frontend-shell-011
 */

import { t } from "@/lib/i18n";
import type { TurnOutput } from "@/lib/contract";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface GuardrailNoteProps {
  /**
   * The guardrails object from the per-turn contract.  We check only
   * `.input.length` and `.output.length` — names are deliberately not exposed.
   */
  guardrails: TurnOutput["guardrails"];
  /** UI language for localised copy. */
  lang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Quiet italic note indicating a guardrail was triggered.
 *
 * Fires when input or output guardrail arrays are non-empty.  The displayed
 * string is the `guardrail.filtered` i18n key (e.g. "This message was
 * filtered.") — calm and factual.  The names of triggered guardrails are
 * intentionally withheld from the UI.
 */
export function GuardrailNote({ guardrails, lang }: GuardrailNoteProps) {
  const hasTriggered =
    guardrails.input.length > 0 || guardrails.output.length > 0;

  if (!hasTriggered) return null;

  const note = t(lang, "guardrail.filtered");

  return (
    <span
      className="
        font-sans text-[0.6rem] italic leading-none
        text-muted-foreground
        select-none
      "
    >
      {note}
    </span>
  );
}
