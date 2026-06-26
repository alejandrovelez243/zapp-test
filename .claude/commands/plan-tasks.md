---
description: SDD gate 3 — write specs/<feature>/tasks.md (numbered checkboxes traceable to requirements + specialist), then STOP.
argument-hint: <feature>
---

You are the SDD **task planner** for the feature `$ARGUMENTS`. This is the THIRD gate. Deliverable: `specs/$ARGUMENTS/tasks.md`. Do NOT write any application code.

## 0. Precondition (hard gate)
- Confirm `specs/$ARGUMENTS/design.md` EXISTS. If it does not, STOP and tell the user to run `/design $ARGUMENTS` first.
- Read BOTH `specs/$ARGUMENTS/requirements.md` and `specs/$ARGUMENTS/design.md` in full.
- Review the available specialists under `.claude/agents/` so every task names a real owner.

## 1. Write tasks.md
Write `specs/$ARGUMENTS/tasks.md` as an ordered, dependency-aware checklist:
- Numbered checkbox tasks: `- [ ] 1. <imperative task>`. Sub-tasks allowed as `- [ ] 1.1 ...`.
- **Each task is traceable**: append the requirement id(s) it satisfies and the **specialist** who will do it, e.g.
  `- [ ] 3. Implement the geo-IP fusion tool with a Logfire span — _req: $ARGUMENTS-4, $ARGUMENTS-5 — owner: backend-engineer_`.
- Order tasks so prerequisites (migrations, data models, config) precede consumers; keep each task small enough for one specialist delegation and one commit.
- Where the design left a config flag (Tier-3 risky features), make enabling it its own task.
- Include the verification task(s): add/extend eval **Cases** (one per acceptance id) and tests, so `/verify` can pass.
- End the file with a **Coverage** note asserting every requirement id appears in at least one task.

## 2. STOP at the gate
- Do NOT begin implementing. Implementation is driven task-by-task via `/implement $ARGUMENTS`.
- Remind the user to **commit the plan only**: `git add specs/$ARGUMENTS/tasks.md && git commit -m "plan: $ARGUMENTS tasks"`.
- End with a one-line summary (task count, specialists involved) and the exact next command: `/implement $ARGUMENTS`.
