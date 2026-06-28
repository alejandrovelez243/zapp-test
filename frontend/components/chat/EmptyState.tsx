"use client";

/**
 * components/chat/EmptyState.tsx
 *
 * Shown when `turns` is empty — the chat surface before the first message.
 *
 * Renders:
 *   - A calm, literary welcome sentence in the serif heading register.
 *   - 3-4 clickable starter-question prompts appropriate to a Philosophy
 *     School.  Each prompt is a <button> that fires `onPrompt(text)`,
 *     which calls `send(text)` in the parent (ChatShell).
 *
 * Keyboard contract: all prompts are <button> elements — fully focusable,
 * Enter/Space activates them, and they carry visible focus rings via the
 * global focus-visible:ring token.  req usability-001.
 *
 * Accessibility: the <section> carries aria-label from the i18n key
 * "emptyState.promptsLabel" so screen-reader users understand the region.
 * Each button label is its full visible text — no additional aria-label needed.
 *
 * Localization: all copy flows through `t(activeLang, key)` — no hardcoded
 * user-facing strings.  req frontend-shell-014, frontend-shell-015.
 *
 * Visual character: editorial, not conversational.  The welcome text is in
 * Newsreader (font-heading) for the philosophical tone; prompts are quiet
 * hairline-bordered buttons, subdued until hovered — consistent with the
 * ink-on-paper aesthetic.
 *
 * Traces: usability-001
 */

import type { I18nKey } from "@/lib/i18n";
import { t } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface EmptyStateProps {
  /**
   * ISO 639-1 code from the per-turn contract `active_lang` field (or the
   * session default "en" before the first turn).  Drives all copy via `t()`.
   */
  activeLang: string;
  /**
   * Called with the full prompt string when the student clicks a starter
   * question.  Wired to `send` in ChatShell.
   */
  onPrompt: (text: string) => void;
}

// ---------------------------------------------------------------------------
// Starter-prompt key list
// ---------------------------------------------------------------------------

/**
 * The four starter questions, typed as I18nKey so the compiler validates
 * each against the i18n union — a missing key is a compile-time error.
 */
const PROMPT_KEYS: readonly I18nKey[] = [
  "emptyState.prompt1",
  "emptyState.prompt2",
  "emptyState.prompt3",
  "emptyState.prompt4",
] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * EmptyState — the welcome surface shown before the first turn.
 *
 * Not a skeleton/loading state — it is the intentional resting state of the
 * chat before inquiry begins.  Replaced by <Transcript> the moment the first
 * student message is appended.
 */
export function EmptyState({ activeLang, onPrompt }: EmptyStateProps) {
  return (
    <section
      aria-label={t(activeLang, "emptyState.promptsLabel")}
      className="mt-10 flex flex-col gap-7"
    >
      {/*
       * Welcome sentence: Newsreader serif at body-large scale.
       * Philosophical and measured — sets the tone before the first exchange.
       */}
      <p className="font-heading text-base leading-relaxed text-foreground">
        {t(activeLang, "emptyState.welcome")}
      </p>

      {/*
       * Starter prompts: quiet, hairline-left-bordered buttons.
       *
       * Left border changes from hairline ink-opacity to the aubergine accent
       * on hover/focus — the single accent used sparingly, as per the design
       * system.  Text shifts from muted to full ink on hover.
       *
       * min-h-[44px] + flex items-center ensure the tap target meets the 44px
       * mobile minimum without adding visual bulk.
       */}
      <ul className="list-none p-0 m-0 flex flex-col gap-1" role="list">
        {PROMPT_KEYS.map((key) => {
          const text = t(activeLang, key);
          return (
            <li key={key} className="list-none">
              <button
                type="button"
                onClick={() => onPrompt(text)}
                className={[
                  // Sizing and layout
                  "min-h-[44px] w-full flex items-center text-left",
                  // Typographic register: quiet sans, muted
                  "font-sans text-sm text-muted-foreground leading-snug",
                  // Hairline left border — transitions to aubergine accent
                  "border-l-2 border-border pl-3 pr-2 py-2",
                  // Interaction states
                  "hover:border-primary hover:text-foreground",
                  "focus-visible:outline-none focus-visible:ring-2",
                  "focus-visible:ring-ring focus-visible:ring-offset-1",
                  // Calm transition (duration matches the reduced-motion override)
                  "transition-colors duration-150",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                {text}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
