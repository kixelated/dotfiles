---
name: pr-new
description: Turn a GitHub issue (or a short task description) into a pull request. Use when the user says "pick up issue 123", "fix #456 and open a PR", "turn this into a PR", or wants an issue filed by /pr-review actioned. Triages the issue, asks before coding if the approach is ambiguous, implements the fix in a fresh worktree (delegating well-scoped work to Codex), verifies with the project's checks, and opens a PR ready for /pr-review or /pr-merge.
argument-hint: "[issue-number | task description] [optional instructions]"
---

# New PR from an Issue

Take an issue from "filed" to "PR open, ready to review". This is the feeder for `/pr-review` and `/pr-merge`: it produces the PR, then hands off — it never merges. Like the sibling skills, it offloads well-scoped implementation to Codex (the user's Codex subscription) while you own the design decisions, the tests, and every line that gets pushed.

Parse `$ARGUMENTS`: a first token that's numeric or `#N` is a GitHub issue number (`gh issue view <n> --json title,body,labels,comments`); otherwise the whole argument is a freeform task description. Extra text after an issue number is additional instructions.

Locate the Codex runtime as in `/pr-review`:
```bash
COMPANION=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
```
If it's unavailable, say so and implement everything yourself rather than blocking.

## Ask before you build

This skill's cardinal rule: **prompt the user whenever something is questionable or the best path forward isn't obvious.** An unwanted PR wastes a review cycle and a worktree; a one-question `AskUserQuestion` with your recommended option first is far cheaper. Ask *before writing code* when:

- The issue admits **multiple plausible approaches** with real tradeoffs, or the root cause is unclear enough that the fix could land in the wrong layer.
- The fix would **change a public API, wire format, or documented behavior** — in this repo that also decides the base branch (semver break → `dev`) and drags in draft/spec updates.
- The issue reads as a **discussion or design question** rather than an agreed-on work item (no accepted approach in the comments, open debate, `discussion`-type labels).
- The scope is **much larger than the issue implies** once you've looked at the code.

If the issue is crisp and the fix is the obvious one, don't ask — just build it.

## Steps

1. **Understand and scope**: read the issue and its comments, then find the relevant code (spawn an Explore agent for broad searches). State the root cause or design in one or two sentences before touching anything — if you can't, that's a sign to investigate more or ask. Check nobody else is already on it (`gh pr list --search "<issue-number>"`, linked PRs on the issue).

2. **Branch**: `git fetch origin`, then create a worktree under `.claude/worktrees/` branched from the freshly fetched base — per this repo's rules, `origin/dev` only for a semver break in a published API, `origin/main` for everything else; when genuinely unsure, ask. Set the upstream to the base (`git branch --set-upstream-to=origin/<base>`) so diff-scoped checks work, and later push with `git push origin HEAD`, not `-u`.

3. **Implement**:
   - **Well-scoped, mechanical, or localized** work → delegate to Codex from the worktree:
     ```bash
     cd "$WT" && node "$COMPANION" task --write "<tight prompt: the root cause, the fix to make, the files involved, and the repo constraints that matter (conventions from CLAUDE.md, e.g. no em dashes, no symptom patches, add a regression test). Do not commit or push.>"
     ```
     Run with `run_in_background: true` and wait for the notification.
   - **Judgment-heavy** work (API shape, cross-package changes, anything where the repo's design rules do the heavy lifting) → implement it yourself.
   - Either way, read the full `git diff` afterward — you own what gets pushed, whoever typed it. If Codex's approach diverged from the agreed design, fix it or redo it; don't shrug it in.

4. **Test and verify**: bug fixes get a regression test that fails without the fix. Run the project's checks from the worktree (`nix develop --command just fix`, then `just check`, or the project's equivalent). Walk the repo's cross-package sync obligations (docs, paired packages, wire-format drafts) — a PR that skips a required sync row should say why in its description.

5. **Commit and open the PR**: follow the repo's CONTRIBUTING for commit messages. Push, then `gh pr create` against the chosen base with a description that states the root cause and the fix (not just the symptom), `Closes #<issue>` when there is one, and the `(written by <the running model>)` line at the end of the body.

6. **Report and hand off**: PR URL, base branch and why, what Codex implemented vs. what you did, test/check results, and anything you deliberately left out of scope. Suggest `/pr-review <number>` or `/pr-merge <number>` as the next step — suggest, don't invoke; the user decides when it's ready to land.

## Rules

- Never merge from this skill, and never enable auto-merge.
- Don't reuse or force-push a branch you didn't create this run.
- One issue, one PR. If the fix uncovers a second independent problem, file it as its own issue (with the `(written by ...)` trailer) rather than growing the diff.
- Clean up the worktree only after the PR is open and pushed; keep it if the user is likely to iterate.
