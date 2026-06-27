/**
 * components/chat/contract/LangIndicator.tsx
 *
 * Discreet active_lang indicator per assistant turn (req frontend-shell-009).
 *
 * Renders the ISO 639-1 language code in a quiet mono register — informative
 * but typographically subordinate to the reply.  Non-intrusive: the code
 * alone is shown visually; the full accessible label ("Session language: en")
 * is provided via aria-label.
 *
 * Purely presentational: no client state, no browser APIs.
 *
 * Traces: frontend-shell-009
 */

import { t } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface LangIndicatorProps {
  /** The session's active language code (ISO 639-1, e.g. "es"). */
  activeLang: string;
  /** UI language for the accessible label (same as session active_lang). */
  lang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * A tiny mono-spaced language code badge.
 *
 * Visual: `en` in uppercase mono at ~0.55rem, muted-foreground/40.
 * Accessible: aria-label carries the full label + code for screen readers.
 * The visible code is visually sufficient; the label avoids a context-free
 * abbreviation in the accessibility tree.
 */
export function LangIndicator({ activeLang, lang }: LangIndicatorProps) {
  const label = t(lang, "lang.indicatorLabel");

  return (
    <span
      aria-label={`${label}: ${activeLang}`}
      className="
        inline-flex items-center
        font-mono text-[0.55rem] tracking-widest uppercase leading-none
        text-muted-foreground
        select-none
      "
    >
      {activeLang}
    </span>
  );
}
