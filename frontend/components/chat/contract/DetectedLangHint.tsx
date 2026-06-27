/**
 * components/chat/contract/DetectedLangHint.tsx
 *
 * Quiet "session locked to {lang}" hint for turns where the user wrote in a
 * different language than the one the session is locked to (req
 * frontend-shell-010).
 *
 * Returns null (renders nothing) when detected_lang === active_lang — clean
 * turns produce no visual noise.
 *
 * Copy: uses `lang.lockedHint` which resolves to e.g. "Session locked to en"
 * — factual and calm, never alarming.
 *
 * Purely presentational: no client state.
 *
 * Traces: frontend-shell-010
 */

import { t } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DetectedLangHintProps {
  /** Language detected in the student's message (ISO 639-1). */
  detectedLang: string;
  /** Language the session is locked to (ISO 639-1). */
  activeLang: string;
  /** UI language for localised copy. */
  lang: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Italic muted note surfacing the session-lock state on a mismatch turn.
 *
 * Rendered only when detectedLang !== activeLang.  The note uses the
 * `lang.lockedHint` key with `{lang}` interpolation so it reads naturally in
 * all three supported languages (req frontend-shell-014).
 */
export function DetectedLangHint({
  detectedLang,
  activeLang,
  lang,
}: DetectedLangHintProps) {
  // No hint when the languages agree — no visual noise on clean turns.
  if (detectedLang === activeLang) return null;

  const hint = t(lang, "lang.lockedHint", { lang: activeLang });

  return (
    <span
      className="
        font-sans text-[0.6rem] italic leading-none
        text-muted-foreground
        select-none
      "
    >
      {hint}
    </span>
  );
}
