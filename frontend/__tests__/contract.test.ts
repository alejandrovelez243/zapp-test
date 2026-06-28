import { describe, it, expect } from "vitest";
import { isTurnOutput, type TurnOutput } from "@/lib/contract";

// Regression: a valid per-turn contract whose detected_country is null (geo
// unavailable — private IP / geo disabled / lookup failure) MUST be accepted.
// Previously the guard required a string and rejected null, surfacing a valid
// 200 response as "Something went wrong" in the chat.
const base: TurnOutput = {
  reply: "¡Hola!",
  detected_lang: "es",
  active_lang: "es",
  lang_confidence: 0.55,
  final_normalized_text: "hola",
  detected_country: "MX",
  confidence_score: 0.55,
  needs_review: false,
  guardrails: { input: [], output: [] },
};

describe("isTurnOutput — detected_country nullability", () => {
  it("accepts a valid contract with detected_country = null", () => {
    expect(isTurnOutput({ ...base, detected_country: null })).toBe(true);
  });

  it("accepts a valid contract with detected_country as a string", () => {
    expect(isTurnOutput({ ...base, detected_country: "MX" })).toBe(true);
  });

  it("rejects detected_country of a wrong type (number)", () => {
    expect(isTurnOutput({ ...base, detected_country: 42 })).toBe(false);
  });

  it("still rejects a body missing a required string field", () => {
    const { reply: _omit, ...noReply } = base;
    expect(isTurnOutput(noReply)).toBe(false);
  });
});
