# Communication

- When a step doesn't need my input, keep going. Put status notes in the same message as your next action.
- Stop and ask only when intent or a consequential choice is unclear, or before anything destructive. Brainstorm options and use an interactive prompt with a recommendation.
- Make references clickable: link issues, PRs, and commits by full URL (`[owner/repo#123](https://github.com/owner/repo/pull/123)`), never a bare `#123`.
- Prioritize refactoring for long-term code maintainability.
- Pro-actively do any background research and explore the state-of-the-art.
- If an instruction in this file is ambiguous, or you had to guess which reading was meant, surface it and propose clearer wording instead of silently picking one.

# GitHub

- Every GitHub post you author must end with a `(Written by <model>)` line naming the running model by display name.
- Don't post on repos outside the `kixelated` and `moq-dev` orgs without approval. A pasted URL or a fork is not approval.
- Pushing to a contributor's fork branch is approved when it's the head of an open PR against a `kixelated` or `moq-dev` repo that allows maintainer edits.
- Before fixing a failure that also breaks the base branch, search open PRs for an existing fix.
- Once scope is settled and local checks pass, commit, push, and open the PR without asking.

# Loops

- Back out when minimal progress is being made, rather than burn tokens.
- Before pausing for a blocking decision or handing off work, commit a checkpoint of meaningful source changes. Record what remains unresolved and which checks passed or were not run.
- Keep disposable scratch out of checkpoints and remove it before handoff. Preserve source changes and local-only submodule commits before releasing a worktree.
- Wait on background work with a blocking command that ends on its terminal state, not short timed polls. Bound each wait under an hour so the prompt cache stays warm, and re-run it on timeout. Stay silent on notifications that change nothing.
- Sub-agents end their turn only with a final result or a question, never with background work still running.

# Shell

- In a worktree-isolated session, run git as its own plain command: no chaining, variables, or xargs.
- Read exit codes directly (`cmd > log 2>&1; echo EXIT=$?`), never through a pipe like `| tail`.

# Development

- Default to worktrees, except `~/work/dotfiles`: it is live config, so edit in place.
- Prefer the net simpler result: reuse what exists, or narrow the scope, when that makes the implementation or API simpler overall.
- Don't set arbitrary acceptance criteria.
