---
name: grill
description: Stress-test and fully scope a plan, decision, or idea through an interactive grilling interview. Use when the user invokes /grill, asks to be grilled, or wants unsettled thinking challenged before action.
---

Interview the user relentlessly until you reach a shared understanding.
Map this as a design tree: every material decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round, interactively if supported: number each question, letter each answer, and prefix one answer with (recommended). Then wait for the user's answers before the next round.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment, dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

When the frontier conflicts with a settled decision, known constraint, or existing design, challenge the user and ask whether the earlier decision or the current scope should change.

The session is done when the frontier is empty: every branch of the design tree has been visited and nothing is left silently assumed. Summarize the resulting decisions, constraints, and next steps, then ask the user to confirm that you have reached a shared understanding. Do not act on the result until the user confirms it.
