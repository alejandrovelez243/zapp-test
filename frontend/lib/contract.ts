/**
 * lib/contract.ts
 *
 * TypeScript mirror of the canonical per-turn JSON contract (9 fields, verbatim
 * names). The frontend is a read-only consumer — it never computes contract fields.
 *
 * Traces: frontend-shell-002 (session_id shape), frontend-shell-003 (POST body),
 *         frontend-shell-004 (render reply), frontend-shell-006 (non-contract error)
 */

// ---------------------------------------------------------------------------
// TurnOutput — the canonical per-turn contract
// All 9 field names are verbatim from the root CLAUDE.md specification.
// ---------------------------------------------------------------------------

export interface TurnOutput {
  /** User-facing answer from the orchestrator. */
  reply: string;
  /** ISO 639-1 code the user wrote in. */
  detected_lang: string;
  /** ISO 639-1 code the session is locked to (backend guarantees es|en|pt). */
  active_lang: string;
  /** Agreement score between LLM-detected language and lingua detector (0–1). */
  lang_confidence: number;
  /** LLM + API fused, locale-normalised input text. */
  final_normalized_text: string;
  /** Fused geo signal — ISO 3166-1 alpha-2 country code. */
  detected_country: string;
  /** Combined logic confidence score (0–1). */
  confidence_score: number;
  /** True when confidence is low, languages diverge, or errors occurred. */
  needs_review: boolean;
  /** Triggered guardrail names — never expose raw internals to students. */
  guardrails: { input: string[]; output: string[] };
}

// ---------------------------------------------------------------------------
// isTurnOutput — runtime type guard
//
// Validates every field's presence and type so a non-contract body from the
// server is detectable and can be converted to ApiError (req frontend-shell-006).
// ---------------------------------------------------------------------------

export function isTurnOutput(x: unknown): x is TurnOutput {
  if (typeof x !== "object" || x === null) return false;
  const o = x as Record<string, unknown>;

  if (typeof o.reply !== "string") return false;
  if (typeof o.detected_lang !== "string") return false;
  if (typeof o.active_lang !== "string") return false;
  if (typeof o.lang_confidence !== "number") return false;
  if (typeof o.final_normalized_text !== "string") return false;
  if (typeof o.detected_country !== "string") return false;
  if (typeof o.confidence_score !== "number") return false;
  if (typeof o.needs_review !== "boolean") return false;

  // Validate guardrails shape
  if (typeof o.guardrails !== "object" || o.guardrails === null) return false;
  const gr = o.guardrails as Record<string, unknown>;
  if (!Array.isArray(gr.input)) return false;
  if (!gr.input.every((v: unknown) => typeof v === "string")) return false;
  if (!Array.isArray(gr.output)) return false;
  if (!gr.output.every((v: unknown) => typeof v === "string")) return false;

  return true;
}

// ---------------------------------------------------------------------------
// ChatTurn — view-model union for the transcript
//
// One discriminated variant per actor: student message, assistant reply
// (carrying the full contract for ContractMeta rendering), or error turn.
// ---------------------------------------------------------------------------

export type ChatTurn =
  | { role: "student"; text: string }
  | { role: "assistant"; text: string; contract: TurnOutput }
  | { role: "error"; text: string };
