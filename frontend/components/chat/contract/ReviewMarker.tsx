"use client";

/**
 * components/chat/contract/ReviewMarker.tsx
 *
 * Quiet hairline side-rule + accessible tooltip for turns where
 * needs_review=true (req frontend-shell-008).
 *
 * Visual: a 1.5px hairline left-border in muted ink (non-alarming) with a
 * small decorative dot.  Completely absent when needs_review is false.
 *
 * !! NEVER uses red / destructive / alarm colors !! (req 008).
 *    The only permitted palette here is muted-foreground at low opacity.
 *
 * The trigger is a `<button>` (base-ui Tooltip.Trigger default), making it
 * keyboard-focusable so screen-reader and keyboard users can access the
 * tooltip (req frontend-shell-020).  The aria-label conveys the full meaning
 * even without the tooltip open.
 *
 * Traces: frontend-shell-008, frontend-shell-020
 */

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { t } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ReviewMarkerProps {
  /** Whether this turn was flagged for review. */
  needsReview: boolean;
  /** UI language for the tooltip text. */
  lang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Renders nothing when needsReview is false — no visual noise on clean turns.
 *
 * When true: a focusable button styled as a hairline side-rule with a muted
 * dot indicator.  On hover or focus, a tooltip surfaces the localised
 * "Flagged for review" copy.
 *
 * Color note: `border-muted-foreground/30` and `text-muted-foreground/45`
 * keep the marker firmly in the "quiet meta" register.  No red, no orange,
 * no destructive color token appears here.
 */
export function ReviewMarker({ needsReview, lang }: ReviewMarkerProps) {
  if (!needsReview) return null;

  const note = t(lang, "review.note");

  return (
    <TooltipProvider>
      <Tooltip>
        {/*
         * The trigger renders as a <button> (base-ui default), providing
         * native keyboard focus and activation semantics.
         *
         * Styling: the left border IS the hairline side-rule (req 008).
         * pl-2 separates the content from the rule; the dot `◦` is a
         * non-alarming decorative cue.  bg-transparent strips the button
         * background.  focus-visible:ring-* uses the aubergine ring token.
         *
         * cursor-help signals "informational" (tooltip present) without
         * implying a click action — consistent with the editorial register.
         */}
        <TooltipTrigger
          type="button"
          aria-label={note}
          className="
            inline-flex items-center pl-2
            border-l-[1.5px] border-muted-foreground/30
            bg-transparent
            font-sans text-[0.6rem] text-muted-foreground
            leading-none select-none cursor-help
            focus-visible:outline-none
            focus-visible:ring-1 focus-visible:ring-ring
            rounded-[2px]
          "
        >
          {/* Decorative dot — aria-hidden; meaning carried by aria-label */}
          <span aria-hidden="true">◦</span>
        </TooltipTrigger>

        <TooltipContent side="top" align="start">
          {note}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
