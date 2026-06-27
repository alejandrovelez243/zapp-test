"use client";

/**
 * components/chat/contract/DetailsDisclosure.tsx
 *
 * Flag-gated collapsible of the four debug contract fields (req
 * frontend-shell-012, frontend-shell-013).
 *
 * Behaviour:
 *   flag OFF (`NEXT_PUBLIC_SHOW_DETAILS` ≠ "1"):
 *     → returns null immediately; the four fields are NOT rendered (req 013).
 *   flag ON:
 *     → renders a keyboard-operable `<Collapsible>` (base-ui primitive, which
 *       renders the trigger as a `<button>`) with a definition list exposing:
 *         lang_confidence, confidence_score, final_normalized_text,
 *         detected_country   (req 012).
 *
 * The `detailsDisclosure` constant is resolved from `NEXT_PUBLIC_SHOW_DETAILS`
 * at build time (Next.js inlines NEXT_PUBLIC_* into both server and client
 * bundles), so when the flag is off the early return is a static dead branch
 * that tree-shaking can eliminate.
 *
 * Keyboard operability: CollapsibleTrigger renders as a `<button>` (Tab to
 * focus, Space/Enter to toggle), satisfying req frontend-shell-020.
 *
 * Traces: frontend-shell-012, frontend-shell-013, frontend-shell-020
 */

import { detailsDisclosure } from "@/lib/flags";
import { t } from "@/lib/i18n";
import type { TurnOutput } from "@/lib/contract";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DetailsDisclosureProps {
  /** The full per-turn contract for this assistant turn. */
  contract: TurnOutput;
  /** UI language for localised labels. */
  lang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Debug details collapsible — operator/admin affordance, hidden from students
 * by default via the `NEXT_PUBLIC_SHOW_DETAILS` build flag.
 *
 * Typography: definition terms in muted mono; values in slightly more visible
 * mono.  A hairline left-border on the `<dl>` visually separates the debug
 * block from the conversational reply without using the accent color.
 */
export function DetailsDisclosure({ contract, lang }: DetailsDisclosureProps) {
  // req 013: when the flag is off, render absolutely nothing for these fields.
  if (!detailsDisclosure) return null;

  const toggleLabel = t(lang, "details.toggle");

  return (
    <Collapsible>
      {/*
       * CollapsibleTrigger renders as a <button>, keyboard-accessible by
       * default (Tab + Space/Enter).  Styled to read as quiet meta copy —
       * not a primary action button.  The `+` prefix is aria-hidden;
       * the label text is the accessible name.
       */}
      <CollapsibleTrigger
        type="button"
        className="
          inline-flex items-center gap-1
          font-mono text-[0.55rem] tracking-widest uppercase leading-none
          text-muted-foreground
          hover:text-foreground/70
          bg-transparent cursor-pointer
          transition-colors
          focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring
          rounded-[2px] select-none
        "
      >
        <span aria-hidden="true" className="leading-none">+</span>
        {toggleLabel}
      </CollapsibleTrigger>

      {/*
       * CollapsibleContent / Panel: animates open/close via base-ui.
       * Reduced-motion override in globals.css silences the animation
       * when prefers-reduced-motion: reduce is set (req frontend-shell-018).
       */}
      <CollapsibleContent className="mt-2">
        {/*
         * Definition list for the four debug fields (req 012).
         *
         * Layout: `dt` (term) + `dd` (value) in a two-column flex row.
         * Border-left hairline uses `border-border` (warm grey), not the
         * accent, preserving the one-accent rule.
         */}
        <dl
          className="
            font-mono text-[0.6rem] leading-relaxed
            text-muted-foreground
            space-y-1 pl-3 border-l border-border
          "
        >
          <div className="flex gap-2 items-baseline">
            <dt className="shrink-0 text-muted-foreground italic">
              {t(lang, "details.label.langConfidence")}
            </dt>
            <dd className="tabular-nums">
              {contract.lang_confidence.toFixed(3)}
            </dd>
          </div>

          <div className="flex gap-2 items-baseline">
            <dt className="shrink-0 text-muted-foreground italic">
              {t(lang, "details.label.confidenceScore")}
            </dt>
            <dd className="tabular-nums">
              {contract.confidence_score.toFixed(3)}
            </dd>
          </div>

          <div className="flex gap-2 items-baseline">
            <dt className="shrink-0 text-muted-foreground italic">
              {t(lang, "details.label.detectedCountry")}
            </dt>
            <dd>{contract.detected_country}</dd>
          </div>

          <div className="flex gap-2 items-baseline">
            <dt className="shrink-0 text-muted-foreground italic">
              {t(lang, "details.label.normalizedText")}
            </dt>
            <dd className="break-all">{contract.final_normalized_text}</dd>
          </div>
        </dl>
      </CollapsibleContent>
    </Collapsible>
  );
}
