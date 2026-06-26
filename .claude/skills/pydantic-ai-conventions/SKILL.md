---
name: pydantic-ai-conventions
description: Use when writing PydanticAI agents, tools, orchestration, guardrails, resilience, or memory for the backend
---

# PydanticAI Conventions (2026, pydantic-ai v1.x)

Canonical patterns for the Philosophy School backend. PydanticAI ONLY (Google ADK is rejected; only A2A as separate HTTP services). Every turn emits the per-turn JSON contract via a typed `output_type`. Keep code typed, inject deps, never use globals.

## 1. Agent construction: typed form + model id in ONE config

Model ids churn (`claude-sonnet-4-6` / `claude-opus-4-6` are PLACEHOLDERS). Keep them in a single config module; confirm the exact id at integration. `ANTHROPIC_API_KEY` comes from env.

```python
# app/agents/config.py — the ONLY place model ids live
ORCHESTRATOR_MODEL = "anthropic:claude-opus-4-6"   # confirm id at integration
WORKER_MODEL       = "anthropic:claude-sonnet-4-6"
JUDGE_MODEL        = "anthropic:claude-haiku-4-6"   # eval judge: distinct tier, temp 0
```

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

orchestrator = Agent(
    ORCHESTRATOR_MODEL,
    deps_type=AgentDeps,
    output_type=TurnOutput,        # structured contract, see §4
    instructions="You route philosophy-school queries...",  # NOT system_prompt — see §2
    retries=2,
)
```

## 2. `instructions=` over `system_prompt=` (the multi-agent leak)

ALWAYS use `instructions=`. `system_prompt=` persists into downstream runs' message history and leaks the wrong persona across agents — when the orchestrator forwards history to the FAQ agent, a stale system prompt bleeds in. `instructions` are re-evaluated per run and do NOT persist. Use `@agent.instructions` for dynamic per-run context.

```python
@orchestrator.instructions
def with_session_context(ctx: RunContext[AgentDeps]) -> str:
    return f"Active language: {ctx.deps.active_lang}. Reply ONLY in this language."
```

## 3. Dependency injection: `@dataclass` AgentDeps via `RunContext`

Carry everything (db session, http client, session_id, resolved locale, active_lang) on a frozen-ish dataclass. Tools read `ctx.deps`. Never reach for module globals.

```python
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

@dataclass
class AgentDeps:
    session: AsyncSession
    http: httpx.AsyncClient        # reused for geo-IP / REST Countries fusion
    session_id: str
    request_ip: str
    active_lang: str               # locked language for the session (ES/EN/PT)
    admin_token: str | None = None
```

## 4. Structured output + `@agent.output_validator` (guard `partial_output`)

`output_type=TurnOutput` makes the model fill the contract. `@agent.output_validator` enforces cross-field rules and may raise `ModelRetry('feedback')` for self-correction. Output validators ALSO run on streaming partials — guard early or you validate half-built objects.

```python
@orchestrator.output_validator
async def enforce_contract(ctx: RunContext[AgentDeps], output: TurnOutput) -> TurnOutput:
    if ctx.partial_output:                     # MANDATORY guard — skip partials
        return output
    if output.reply and output.active_lang != ctx.deps.active_lang:
        raise ModelRetry(f"Reply must be in {ctx.deps.active_lang}, not {output.active_lang}.")
    return output                              # reconciliation/fusion happens here too
```

`FallbackModel` will NOT rescue a structurally-bad 200 response — output validators are the safety net for that.

## 5. Agent-as-tool orchestration: forward `deps` AND `usage`

Sub-agents are re-run inside an orchestrator tool. ALWAYS pass `deps=ctx.deps` (shared deps) AND `usage=ctx.usage` (aggregates token/cost into one `RunUsage` and keeps `UsageLimits` correct). Omitting `usage` gives per-agent wrong cost and broken limits.

```python
@orchestrator.tool
async def ask_faq(ctx: RunContext[AgentDeps], question: str) -> str:
    """Answer from uploaded philosophy documents (RAG)."""
    r = await faq_agent.run(question, deps=ctx.deps, usage=ctx.usage)
    return r.output

@orchestrator.tool
async def enroll_in_event(ctx: RunContext[AgentDeps], event_id: str, email: str) -> str:
    """Enroll the user and return an .ics. Destructive — gated by a before-tool hook (§7)."""
    r = await events_agent.run(
        f"Enroll {email} in {event_id}", deps=ctx.deps, usage=ctx.usage
    )
    return r.output
```

Cap every entry run with `UsageLimits`:

```python
from pydantic_ai.usage import UsageLimits

result = await orchestrator.run(
    user_text, deps=deps, message_history=history,
    usage_limits=UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=20000),
)
```

Reserve `pydantic-graph` ONLY for the human-in-the-loop enroll confirmation — not for routine routing.

## 6. Resilience: FallbackModel, timeouts, ModelRetry, boundary catch -> needs_review

```python
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings

model = FallbackModel(
    AnthropicModel(PRIMARY_ID, settings=AnthropicModelSettings(timeout=30.0)),
    AnthropicModel(SECONDARY_ID, settings=AnthropicModelSettings(timeout=30.0)),
)
```

- `FallbackModel(primary, secondary)` retries transient API errors; `Agent(retries=2)` and `@agent.tool(retries=2)` add self-correction; raise `ModelRetry('...')` inside a tool/validator to ask the model to fix itself.
- At the FastAPI boundary, catch and degrade to a valid contract with `needs_review=true`:

```python
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

try:
    result = await orchestrator.run(user_text, deps=deps, usage_limits=limits,
                                    message_history=history)
    out = result.output
except (ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded) as e:
    logfire.warning("orchestrator degraded", error=str(e))
    out = degraded_turn(active_lang=deps.active_lang)   # needs_review=True, safe reply
```

## 7. Guardrails: native Hooks (ordering) + pydantic-ai-guardrails GuardedAgent

There is NO core `guardrails=[...]` Agent arg. Two layers:

Native **Capabilities/Hooks** interception — ordering matters: before-hooks fire in registration order, after-hooks reversed, wrap-hooks nest.

```python
from pydantic_ai import Hooks

hooks = Hooks()

@hooks.on.before_model_request          # inbound PII redaction before the model sees text
async def redact(ctx): ...

@hooks.on.before_tool_execute           # gate the destructive enroll action
async def confirm_enroll(ctx): ...

@hooks.on.on_model_request_error        # trigger fallback / mark needs_review
async def on_error(ctx): ...
```

Measurable PII/injection/toxicity/secret-redaction = THIRD-PARTY `pydantic-ai-guardrails` (v0.2.x) `GuardedAgent`. Install extras `[telemetry]` (then `configure_telemetry(enabled=True)` for Logfire spans) and `[evals]` (pydantic-evals integration).

```python
from pydantic_ai_guardrails import GuardedAgent, pii_detector, prompt_injection, toxicity

guarded = GuardedAgent(
    orchestrator,
    input_guardrails=[pii_detector(), prompt_injection()],
    output_guardrails=[toxicity()],
    on_block="raise",          # 'raise' | 'log' | 'silent'
    max_retries=2,
    parallel=True,
)
```

Populate the contract's `guardrails.input` / `guardrails.output` with the names of any guardrails that fired.

## 8. Multi-turn memory via `all_messages()` + `message_history=`

Persist `result.all_messages()` keyed by `session_id`; replay with `message_history=`. Do NOT reconstruct history from raw strings.

```python
history = await load_messages(deps.session_id)            # list[ModelMessage] or None
result = await orchestrator.run(user_text, deps=deps, message_history=history)
await save_messages(deps.session_id, result.all_messages())
```

## 9. Observability instrumentation (call once at startup)

```python
import logfire
logfire.configure()                         # SCRUBS PII by default; sample in prod
logfire.instrument_pydantic_ai()            # agent/tool spans + token cost (genai-prices)
logfire.instrument_fastapi(app)
logfire.instrument_httpx(capture_all=True)  # captures geo-IP + REST Countries fusion calls
logfire.instrument_sqlalchemy(engine)
```

Logfire = engineering/LLM tracing (feeds eval p50/p95 + cost-per-conversation). PostHog has NO PydanticAI wrapper and does NOT scrub PII — send METADATA-ONLY for student messages.

## 10. Skeleton: orchestrator + faq + events

```python
faq_agent = Agent(WORKER_MODEL, deps_type=AgentDeps, output_type=str,
                  instructions="Answer ONLY from retrieved philosophy docs; if no match, say so.")

@faq_agent.tool
async def retrieve(ctx: RunContext[AgentDeps], query: str) -> list[str]:
    """Top-k pgvector cosine retrieval; empty -> caller lowers confidence + needs_review."""
    return await search_chunks(ctx.deps.session, query, k=5)

events_agent = Agent(WORKER_MODEL, deps_type=AgentDeps, output_type=str,
                     instructions="Enroll the user and produce a localized .ics summary.")

@events_agent.tool
async def make_ics(ctx: RunContext[AgentDeps], event_id: str, email: str) -> str:
    """Enroll + build .ics; localize times to detected_country/timezone."""
    return await enroll_and_build_ics(ctx.deps, event_id, email)

# orchestrator (§1) exposes ask_faq / enroll_in_event tools (§5) and emits TurnOutput.
```

## Gotchas (read before shipping)

- Model ids are placeholders in ONE config module — confirm exact id at integration.
- Use `instructions=`, never `system_prompt=` (persona leaks across agents via forwarded history).
- Output validators run on streaming partials — `if ctx.partial_output: return output` FIRST.
- Forward `usage=ctx.usage` to EVERY sub-agent run, or cost is wrong and `UsageLimits` breaks.
- `FallbackModel` only rescues retryable errors, NOT a structurally-bad 200 — pair with output validators.
- There is NO `guardrails=[...]` Agent arg; native = Hooks, measurable = `pydantic-ai-guardrails` GuardedAgent.
- Hook ordering: before = registration order, after = reversed, wrap = nested.
- Document ingestion is a BACKGROUND job, never inline in the request; treat ingested docs as immutable.
- Low/empty retrieval -> lower `confidence_score` + `needs_review=true`, never invent an answer.
- Catch `ModelHTTPError` / `UnexpectedModelBehavior` / `UsageLimitExceeded` at the FastAPI boundary -> degrade to a valid contract with `needs_review=true`.
- Unsupported language -> set `active_lang` to the configured fallback AND `needs_review=true`; degrade gracefully. Supported languages: ES, EN, PT.
- ADK is rejected — do not import it; PydanticAI and ADK do not compose in-process (only A2A as separate HTTP services).
