---
name: start-task
description: Start a numbered task from a Berean plan. Use when the user says "start task N", "do task N" or "next task".
disable-model-invocation: true
---

Orient on task **N** from a plan, then implement it. The plan is volatile and the specs it cites are the source of truth.

## Steps

1. **Find the plan.** Numbered tasks are `Task N` headings in `specs/*/PLAN.md` and `specs/*/*-PLAN.md`. `grep -n "^#* Task N\b" specs/*/*PLAN.md`.
   - One match: use it.
   - Several: take the plan whose task has unchecked `- [ ]` boxes and whose name matches the current branch. If that still leaves two, ask which.
   - None: say so and stop. Do not infer a task from the specs.

2. **Read the whole task section** (heading to the next task heading), plus the plan's Global Constraints if it has them.

3. **Gate on dependencies.** For each task in `**Depends on:**`, its section must say `**Status:** landed` or have every box checked. Confirm against `git log` and the code where the section names a package. A dependency that has not landed **blocks the task**: report it and stop.

4. **Read what the task cites**: the spec sections and ADRs it names, and the `AGENTS.md` of each service it touches (nearest file wins). Read code only for the packages the task changes.

5. **State the ground before writing code**: the task's acceptance boxes, in the plan's words; the files you expect to touch; anything the spec is silent on. Silence is a question for the user, never an inference (CLAUDE.md).

6. **Implement** with the `superpowers:executing-plans` skill, one acceptance box at a time. Run `make check` before calling any box done.

7. **Close the task in the plan**: check the boxes, write the `**Status:**` line, and update any spec the work overtook, in the same change.

Done means every acceptance box is checked against a passing command, and the plan's status line matches what landed.
