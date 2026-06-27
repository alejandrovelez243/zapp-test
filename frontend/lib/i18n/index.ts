/**
 * lib/i18n/index.ts
 *
 * Runtime i18n for UI chrome copy.  Keyed by the session's `active_lang` field
 * from the per-turn contract.  No URL-locale routing — the backend locks the
 * session language; the frontend mirrors it.
 *
 * Design choices (from design.md "Open Decisions"):
 *   - Lightweight runtime dictionary, NOT next-intl / URL-locale routing.
 *   - `active_lang` outside {es, en, pt} falls back to `en` (req 016).
 *   - Missing key in a non-English dict falls back to the `en` string (never blank).
 *   - Simple {var} interpolation via vars? Record<string, string|number>.
 *
 * Traces: frontend-shell-014 (chrome in active_lang),
 *         frontend-shell-015 (chrome updates on active_lang change),
 *         frontend-shell-016 (en fallback for non-ES/EN/PT active_lang)
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Supported runtime languages. */
export type Lang = "es" | "en" | "pt";

/**
 * All chrome keys the shell components consume.
 * Adding a key here forces the Dict type to require it — compile error if any
 * locale dict is incomplete.
 */
export type I18nKey =
  | "composer.placeholder"
  | "composer.sendLabel"
  | "composer.hint"
  | "state.sending"
  | "error.generic"
  | "error.network"
  | "lang.indicatorLabel"
  | "lang.lockedHint"
  | "guardrail.filtered"
  | "review.note"
  | "details.toggle"
  | "details.label.langConfidence"
  | "details.label.confidenceScore"
  | "details.label.detectedCountry"
  | "details.label.normalizedText"
  | "a11y.transcriptLabel"
  | "a11y.newReply";

/** A complete locale dictionary — every I18nKey must be present. */
export type Dict = Record<I18nKey, string>;

// ---------------------------------------------------------------------------
// Locale dictionaries
// (en.ts / es.ts / pt.ts import `Dict` as a type-only import from this file —
//  the circular reference is type-only and erased at runtime, which is safe.)
// ---------------------------------------------------------------------------

import en from "./en";
import es from "./es";
import pt from "./pt";

const dicts: Record<Lang, Dict> = { en, es, pt };

// ---------------------------------------------------------------------------
// t() — the chrome resolver
// ---------------------------------------------------------------------------

/**
 * Resolve a chrome string for the given `activeLang`.
 *
 * @param activeLang  - ISO 639-1 code from the per-turn contract `active_lang`
 *                      field.  If it is not one of "es" | "en" | "pt", the
 *                      function falls back to English (req frontend-shell-016).
 * @param key         - A member of the I18nKey union; a non-member is a
 *                      compile-time error.
 * @param vars        - Optional interpolation variables.  Occurrences of
 *                      `{varName}` in the resolved string are replaced with
 *                      the corresponding value.  Example:
 *                        t("en", "lang.lockedHint", { lang: "es" })
 *                        // => "Session locked to es"
 * @returns           The resolved, interpolated string.  Never undefined or
 *                    blank: unknown keys fall back to the English string.
 */
export function t(
  activeLang: string,
  key: I18nKey,
  vars?: Record<string, string | number>,
): string {
  // Req frontend-shell-016: fall back to "en" for any activeLang outside the
  // supported set.
  const lang: Lang = activeLang === "es" || activeLang === "pt" ? activeLang : "en";

  // Resolve from the target locale first; fall back to English for a missing
  // key (defensive — Dict enforces completeness at compile time, but a partial
  // override at runtime would otherwise produce undefined).
  const resolved: string =
    (dicts[lang][key] as string | undefined) ?? (dicts.en[key] as string);

  if (!vars) return resolved;

  // Simple {varName} interpolation — no nested braces, no escaping needed for
  // the chrome strings defined here.
  return resolved.replace(
    /\{(\w+)\}/g,
    (_, name: string) => String(vars[name] ?? `{${name}}`),
  );
}
