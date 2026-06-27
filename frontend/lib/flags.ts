/**
 * Feature flags resolved from build-time environment variables.
 *
 * NEXT_PUBLIC_* vars are inlined at build time — changing them requires a
 * redeploy; they are never secrets.
 *
 * Traces: frontend-shell-012, frontend-shell-013
 */

/**
 * When true, DetailsDisclosure renders the collapsible block of debug contract
 * fields (lang_confidence, confidence_score, final_normalized_text,
 * detected_country) on each assistant turn.
 *
 * Set NEXT_PUBLIC_SHOW_DETAILS=1 in your environment to enable.
 * Default: off (false) — the debug fields are not rendered for students.
 */
export const detailsDisclosure: boolean =
  process.env.NEXT_PUBLIC_SHOW_DETAILS === "1";
