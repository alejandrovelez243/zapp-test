# Evaluation Requirements

## Summary

An automated, repeatable evaluation system for the conversational agent — the brief's graded
"Evaluation System". Two parts: (1) an **offline suite** runnable as ONE command that produces ONE
report over committed datasets (happy-path, multilingual, adversarial), computing task success,
language fidelity, guardrail effectiveness, LLM-judge subjective quality, and operational
latency/cost, with configurable thresholds and a non-zero exit on breach (CI-ready); and (2) a
**runtime end-of-conversation judge** that grades a finished chat session (on inactivity timeout or a
goodbye intent), persists the grade, and emits it to observability.

## Persona & job-to-be-done

As a maintainer (and the hiring reviewer), I need a one-command, reproducible eval suite with a clear
report and CI gate so that agent quality is measured with evidence, not claims. As the platform, I
need each finished conversation graded at runtime so quality is tracked in production.

## In / Out of scope

In scope: the `pydantic-evals` offline runner (`uv run python -m evals.run`) + a single consolidated
report + a committed example report; committed YAML datasets (happy/multilingual/adversarial — the
14 `multilingual-*` cases already exist); the metrics (task success %, language fidelity %, guardrail
precision/recall, LLM-judge 1–5 @ temp 0 with a documented rubric, latency p50/p95, estimated cost per
conversation); one-place configurable thresholds + non-zero exit; CI running the full suite (incl. the
judge) on every push/PR using the gateway key from secrets; the runtime end-of-conversation judge
(timeout + goodbye intent) persisting + emitting grades.

Out of scope (own specs): the guardrail LOGIC itself (`guardrails` — evaluation MEASURES guardrail
effectiveness; the adversarial guardrail cases + meaningful precision/recall expand when `guardrails`
lands); the FAQ-RAG / events behaviors evaluated later as their specs land; the per-turn contract
(unchanged); geo/country fusion.

## Config flags & values

- `runtime_eval_enabled` (flag, Tier-3): the end-of-conversation judge runs only when enabled.
- `conversation_idle_timeout` (value, e.g. 900s): inactivity after which a session is "ended".
- One thresholds config: `task_success_min`, `language_fidelity_min`, `guardrail_precision_min`,
  `guardrail_recall_min`, `judge_mean_min` (1–5), `latency_p95_max_ms`, `cost_per_conversation_max`.
- `judge_model` (default `gateway/openai:gpt-4.1-mini`), temperature 0 — in the one config module.

## User Stories

- As a maintainer, I want one command to run the whole eval suite and get one report, so that I can
  check quality quickly and in CI.
- As a maintainer, I want the suite to exit non-zero when a metric breaches its threshold, so that CI
  blocks regressions.
- As the hiring reviewer, I want a pre-generated example report, so that I can see the evidence without
  running anything.
- As the platform, I want each finished conversation graded automatically, so that runtime quality is
  tracked.

## Acceptance Criteria

1. WHEN an engineer runs `uv run python -m evals.run` THE SYSTEM SHALL execute all committed datasets (happy-path, multilingual, adversarial) and produce ONE consolidated report.   <!-- eval: evaluation-001 -->
2. THE SYSTEM SHALL report task success as the percentage of cases passing their assertions.   <!-- eval: evaluation-002 -->
3. THE SYSTEM SHALL report language fidelity as the percentage of replies in the expected language.   <!-- eval: evaluation-003 -->
4. THE SYSTEM SHALL report guardrail effectiveness as precision and recall over the adversarial cases.   <!-- eval: evaluation-004 -->
5. THE SYSTEM SHALL report subjective quality via an LLM-as-judge scored on a documented 1–5 rubric at temperature 0.   <!-- eval: evaluation-005 -->
6. THE SYSTEM SHALL report operational metrics: latency p50 and p95, and estimated cost per conversation.   <!-- eval: evaluation-006 -->
7. THE SYSTEM SHALL read all pass/fail thresholds from a single configurable location.   <!-- eval: evaluation-007 -->
8. IF any reported metric breaches its configured threshold THEN THE SYSTEM SHALL exit with a non-zero status.   <!-- eval: evaluation-008 -->
9. WHEN the suite finishes THE SYSTEM SHALL write the report to a file AND print a summary.   <!-- eval: evaluation-009 -->
10. THE SYSTEM SHALL pin the LLM-judge model and run it at temperature 0 for reproducibility, configured in one place (default `gateway/openai:gpt-4.1-mini`).   <!-- eval: evaluation-010 -->
11. THE SYSTEM SHALL store the eval datasets as committed files covering happy-path, multilingual (ES/EN/PT), and adversarial cases.   <!-- eval: evaluation-011 -->
12. WHEN CI runs on push or pull request THE SYSTEM SHALL execute the full eval suite (including the LLM judge, using the gateway key from secrets) and fail the pipeline on any threshold breach.   <!-- eval: evaluation-012 -->
13. THE SYSTEM SHALL commit a pre-generated example report demonstrating the metrics.   <!-- eval: evaluation-013 -->
14. WHILE a chat session has been inactive longer than `conversation_idle_timeout` THE SYSTEM SHALL treat the conversation as ended and trigger a runtime evaluation of that session.   <!-- eval: evaluation-014 -->
15. WHEN a user expresses an end-of-conversation intent (e.g. goodbye / "no necesito más ayuda") THE SYSTEM SHALL call the `end_session` tool, which signals the boundary to trigger a runtime evaluation of that session; the prior keyword-heuristic trigger (`is_goodbye`) is replaced by this tool invocation.   <!-- eval: evaluation-015 -->
16. WHEN a conversation ends THE SYSTEM SHALL grade the finished session with the LLM judge (1–5 rubric, temperature 0) and persist the grade.   <!-- eval: evaluation-016 -->
17. WHEN a runtime evaluation completes THE SYSTEM SHALL emit the grade as metadata to observability (Logfire + PostHog) WITHOUT student message content.   <!-- eval: evaluation-017 -->
18. WHERE runtime evaluation is enabled THE SYSTEM SHALL run the end-of-conversation judge; WHERE disabled THE SYSTEM SHALL skip it.   <!-- eval: evaluation-018 -->
19. IF the LLM judge errors or times out THEN THE SYSTEM SHALL record that case as un-judged (counted as not-passing) AND continue the run without crashing.   <!-- eval: evaluation-019 -->
20. IF a case's reply is not in the expected language THEN THE SYSTEM SHALL count it as a language-fidelity failure.   <!-- eval: evaluation-020 -->

## Case-id map

`evaluation-001..020` are verified by **pytest + CI checks of the eval system itself** (the runner,
metric computation, threshold/exit behavior, dataset presence, the runtime-trigger logic) — NOT by
LLM-judge Cases. The LLM-judge Cases are the *content* this feature runs (the committed datasets:
`multilingual-*`, future `guardrails-*`, happy-path). Ids are append-only.

## Non-functional / contract

- **Reads** the per-turn `TurnOutput` fields to score: `reply`, `detected_lang`, `active_lang`,
  `lang_confidence`, `needs_review`, `guardrails`. The runtime judge reads a session's persisted
  `message_history`.
- **Writes** (not the per-turn contract): the offline report file + the committed example report; a
  persisted runtime grade record (Postgres) + observability metadata (Logfire/PostHog, metadata-only).
- Languages: language fidelity asserts replies are in the expected language; the multilingual dataset
  covers ES/EN/PT + the unsupported→fallback case (`needs_review=true`).
- Reproducibility: judge model pinned + temperature 0; thresholds in one config; the offline suite and
  CI gate share the same runner.
- Cost/Privacy: cost-per-conversation estimated from token usage (`RunUsage`) × pinned pricing (or
  gateway-reported cost); never send student message content to PostHog.
