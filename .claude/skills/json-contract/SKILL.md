---
name: json-contract
description: Use when defining or validating the per-turn TurnOutput JSON contract and its reconciliation rules
---

# Per-Turn TurnOutput JSON Contract

Every conversational turn MUST emit this exact JSON object. It is the single
integration seam between the PydanticAI orchestrator, FastAPI, the Next.js
client, and the observability/eval pipelines. Do not add, rename, or drop
fields; downstream PostHog dashboards and pydantic-evals Cases key off these
names.

## Canonical contract (verbatim — keep textually identical)

```json
{
  "reply": "string",                  // user-facing answer
  "detected_lang": "es",              // ISO 639-1 the user wrote in
  "active_lang": "es",                // language the session is locked to
  "lang_confidence": 0.97,            // agreement score LLM vs detector
  "final_normalized_text": "string",  // LLM + API fused, locale-normalized
  "detected_country": "MX",           // fused geo signal (ISO 3166-1 alpha-2)
  "confidence_score": 0.0,            // combined logic
  "needs_review": false,              // true on low confidence / divergence / errors
  "guardrails": { "input": [], "output": [] }  // triggered guardrail names
}
```

Supported languages: ES, EN, PT. Unsupported language -> set active_lang to the
configured fallback AND needs_review=true, degrade gracefully.

## The Pydantic model (this is `output_type`)

```python
from pydantic import BaseModel, Field
from pydantic_extra_types.country import CountryAlpha2  # ISO 3166-1 alpha-2


class GuardrailReport(BaseModel):
    """Names of guardrails that triggered this turn (empty when clean)."""
    input: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)


class TurnOutput(BaseModel):
    # Only `reply` is required of the model. Every other field carries a safe default so
    # the LLM may omit the validator-owned fields (active_lang / lang_confidence) it is
    # instructed NOT to set. Without defaults, an omitted required field triggers a schema
    # ModelRetry loop ("Field required") that exhausts the retry budget and degrades the turn.
    reply: str = Field(..., description="User-facing answer, in active_lang")
    detected_lang: str = Field(
        default="en", min_length=2, max_length=2,
        description="ISO 639-1 the user wrote in",
    )
    active_lang: str = Field(
        default="en", min_length=2, max_length=2,
        description="Language the session is locked to (es|en|pt or fallback); validator-owned",
    )
    lang_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Agreement score: LLM detected_lang vs lingua detector (validator-owned)",
    )
    final_normalized_text: str = Field(
        default="",
        description="LLM-cleaned user text fused with resolved locale "
                    "(relative dates resolved to detected timezone)",
    )
    detected_country: CountryAlpha2 | None = Field(
        default=None, description="Fused geo-IP signal (ISO 3166-1 alpha-2)",
    )
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Combined reconciliation confidence",
    )
    needs_review: bool = Field(
        default=False,
        description="True on low confidence / signal divergence / caught errors",
    )
    guardrails: GuardrailReport = Field(default_factory=GuardrailReport)
```

Notes: `lang_confidence` and `confidence_score` are constrained `ge=0 le=1`.
ISO 639-1 codes are 2-char lowercase; `detected_country` uses ISO 3166-1
alpha-2 and is nullable because the geo-IP call may fail (then needs_review).

## Field-by-field semantics

- **reply** — the answer shown to the user; its language MUST equal
  `active_lang` (enforced by an output_validator below).
- **detected_lang** — what the LLM judged the user *wrote* this turn (ISO 639-1).
- **active_lang** — the language the session is locked to; set on the first
  supported turn and held stable so the conversation does not flip-flop.
- **lang_confidence** — agreement score between the LLM's `detected_lang` and
  the deterministic `lingua` detector (1.0 = exact agreement).
- **final_normalized_text** — the LLM's cleaned/normalized user text reconciled
  with the resolved locale (e.g. relative dates resolved to the user's timezone
  from REST Countries enrichment).
- **detected_country** — fused geo-IP signal (ipinfo.io / ipapi.co on the
  request IP); also localizes `.ics` event times.
- **confidence_score** — combined logic over all signals (language agreement,
  geo availability, RAG retrieval confidence, guardrail state).
- **needs_review** — escalation flag; true on low confidence, signal divergence,
  unsupported language, or any caught error.
- **guardrails** — names of triggered guardrails, split `input` / `output`.

## Reconciliation rules (apply in the output_validator / fusion tool)

Fusion happens inside a PydanticAI tool (a traceable Logfire span); reconcile in
the output_validator:

1. **Agreement** — LLM `detected_lang` == `lingua` detection AND geo-IP locale
   is consistent -> raise `confidence_score`; `lang_confidence` near 1.0.
2. **Disagreement** — LLM vs detector (or geo) diverge -> lower
   `confidence_score`, set `needs_review=true`. Trust the deterministic detector
   for `active_lang` tie-breaks but record the divergence.
3. **Unsupported language** — detected language not in {ES, EN, PT} -> set
   `active_lang` to the configured fallback AND `needs_review=true`; degrade
   gracefully (still answer in the fallback language).
4. **Any caught error** — geo-IP timeout, REST Countries failure, low/empty RAG
   retrieval, or a degraded model boundary exception -> `needs_review=true` and
   damp `confidence_score`; never raise to the user.

## output_validator: reply-language must equal active_lang

```python
from pydantic_ai import Agent, ModelRetry, RunContext

agent = Agent("<provider>:<model-id>", deps_type=AgentDeps, output_type=TurnOutput)  # any PydanticAI provider prefix works


@agent.output_validator
async def enforce_reply_language(
    ctx: RunContext[AgentDeps], output: TurnOutput
) -> TurnOutput:
    # Output validators also run on streaming partials — guard first.
    if ctx.partial_output:
        return output

    # Cross-field rule: the reply must be written in the locked language.
    reply_lang = detect_language(output.reply)  # deterministic lingua check
    if reply_lang != output.active_lang:
        raise ModelRetry(
            f"reply is in '{reply_lang}' but active_lang is "
            f"'{output.active_lang}'. Rewrite reply in {output.active_lang}."
        )

    # Reconcile confidence/needs_review on divergence (rule 2 / rule 4).
    if output.lang_confidence < 0.5 or output.detected_country is None:
        output.needs_review = True
        output.confidence_score = min(output.confidence_score, 0.5)
    return output
```

## Populating the guardrails sub-object

The `guardrails` field reports which guardrails fired, never the redacted
content (Logfire holds content; this contract carries only names). Populate from
the pydantic-ai-guardrails results:

- **input** — names of triggered inbound guardrails, e.g.
  `["pii_detector", "prompt_injection"]` (PII redaction, injection, secrets).
- **output** — names of triggered outbound guardrails, e.g. `["toxicity"]`.
- Clean turn -> both lists empty: `{"input": [], "output": []}`.
- Any triggered input/output guardrail SHOULD also push `needs_review=true` when
  `on_block='log'` (we answered but flagged) so reviewers can audit the turn.
