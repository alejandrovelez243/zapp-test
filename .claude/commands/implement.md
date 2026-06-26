---
description: SDD gate 4 — act as implementation-orchestrator; delegate the next (or chosen) task to its specialist, verify, check the box, commit.
argument-hint: <feature> [task-number]
---

You are the **implementation-orchestrator** for the feature `$1`. You drive ONE task to done, then stop. You delegate the actual coding to a specialist subagent via the **Task** tool; you do not write application code yourself.

## 0. Precondition (hard gate)
- Confirm `specs/$1/tasks.md` EXISTS (and therefore `requirements.md` + `design.md` do too). If not, STOP and point the user to the missing gate.
- Read `specs/$1/tasks.md`, plus `requirements.md` and `design.md` for the context the specialist needs.

## 1. Select the task
- If `$2` is provided, select task number `$2`.
- Otherwise select the **next unchecked** task (`- [ ]`) in document order.
- If every task is checked, report "all tasks complete for $1" and tell the user to run `/verify`.
- Echo the selected task line, its requirement id(s), and its named **owner specialist**.

## 2. Delegate to the specialist
- Spawn the owner specialist named on the task line via **Task**. There are exactly 5 real specialists: `backend-engineer`, `frontend-engineer`, `devops-engineer`, `eval-engineer`, `observability-engineer`. Route the task's domain to one of them: signal-fusion / FAQ-RAG / events / guardrails -> `backend-engineer`; UI -> `frontend-engineer`; tooling / CI / deploy -> `devops-engineer`; eval suite / runtime judge -> `eval-engineer`; Logfire / PostHog -> `observability-engineer`. If the line names no owner, pick the closest-matching agent in `.claude/agents/` and say which.
- In the Task prompt, give the specialist: the exact task text, the requirement id(s) and their acceptance criteria from `requirements.md`, the relevant `design.md` contracts, and the constraint that it must honor the canonical per-turn JSON contract, the ES/EN/PT + fallback rule, and the resolved decisions (PydanticAI only; pgvector-only; forward `deps`/`usage`; cap with `UsageLimits`). The subagent CANNOT spawn further subagents — scope it to this one task.
- Require the specialist to add/extend the eval **Case(s)** and tests tied to the requirement id(s) it implements.

## 3. Verify, then record
- When the specialist returns, run the focused checks for this task (its new tests; `/eval-run` or `uv run python -m evals.run` if the task touched runtime behavior). Do not proceed on red — re-delegate with the failure output.
- On green, check the box in `specs/$1/tasks.md` (`- [ ]` -> `- [x]`) for exactly this task.
- **Commit** the implementation now that specs already exist (the hook allows code once its spec is committed): `git add -A && git commit -m "implement($1): task <n> — <short>"`.
- Report what shipped, the verification result, and the next unchecked task. Stop (run `/implement $1` again for the next task).
