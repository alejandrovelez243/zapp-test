/**
 * components/chat/ThinkingTurn.tsx
 *
 * In-transcript pending affordance shown while `status === 'sending'`.
 *
 * Renders in the same visual register as an AssistantTurn (border-top
 * hairline, vertical padding) but in the muted typographic key — indicating
 * "the assistant is composing, not yet speaking".
 *
 * Motion: three small dots pulse with a staggered delay.  The global
 * `prefers-reduced-motion: reduce` block in globals.css cuts
 * `animation-duration` to 0.01ms and sets `.animate-pulse { animation: none }`
 * — both guard paths are covered.
 *
 * Screen readers: the outer `role="status"` makes this a live region that
 * announces its text once, without interrupting ongoing speech.  The visual
 * dots are `aria-hidden`; the text content provides the accessible label.
 *
 * Presentational: no client-side state, no browser APIs.  May be rendered
 * from a client boundary (ChatShell) without requiring its own "use client".
 *
 * Traces: usability-002
 */

import { t } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ThinkingTurnProps {
  /**
   * ISO 639-1 code — resolves "state.sending" via `t()` so the copy matches
   * the session's active language.
   */
  activeLang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * ThinkingTurn — ephemeral in-transcript indicator while the assistant
 * is composing a reply.  Mounts when `status === 'sending'`, unmounts when
 * the assistant turn (or error) arrives.
 */
export function ThinkingTurn({ activeLang }: ThinkingTurnProps) {
  const label = t(activeLang, "state.sending");

  return (
    /*
     * role="status" + aria-live="polite": announces the label once when the
     * element is inserted.  aria-atomic="true" ensures the whole text is read
     * rather than just the changed portion.
     * data-testid allows targeted assertions in component tests.
     */
    <article
      role="status"
      aria-live="polite"
      aria-atomic="true"
      data-testid="thinking-turn"
      className="border-t border-border pt-7 pb-6"
    >
      <div className="flex items-center gap-2.5">
        {/*
         * Three pulsing dots — purely decorative; hidden from assistive
         * technology (aria-hidden).  Staggered animation delays give a
         * "wave" feel at low cost.
         *
         * globals.css disables these under prefers-reduced-motion via:
         *   .animate-pulse { animation: none !important }
         * plus the universal animation-duration: 0.01ms block.
         */}
        <span
          className="flex gap-[3px] items-center"
          aria-hidden="true"
        >
          <span
            className="h-[5px] w-[5px] rounded-full bg-muted-foreground/60 animate-pulse"
            style={{ animationDelay: "0ms", animationDuration: "1.4s" }}
          />
          <span
            className="h-[5px] w-[5px] rounded-full bg-muted-foreground/60 animate-pulse"
            style={{ animationDelay: "280ms", animationDuration: "1.4s" }}
          />
          <span
            className="h-[5px] w-[5px] rounded-full bg-muted-foreground/60 animate-pulse"
            style={{ animationDelay: "560ms", animationDuration: "1.4s" }}
          />
        </span>

        {/*
         * Textual label: same serif voice as the assistant, but muted and
         * italic — visually distinct from a completed reply.  Provides the
         * accessible text content announced by role="status".
         */}
        <span className="font-heading text-sm text-muted-foreground italic leading-none">
          {label}
        </span>
      </div>
    </article>
  );
}
