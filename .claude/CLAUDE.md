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
- Finish checks and reviews locally before the final publication. After publishing the completed attempt, report the PR and terminate the agent.
- Never wait or poll for GitHub CI, online reviews, or merge-queue activity. A separate process owns that monitoring and may dispatch a new local attempt for available feedback.
- Approve `action_required` fork CI runs on `kixelated` and `moq-dev` repos without asking, but only for the current head of an open PR.
- When `gh` hits the GraphQL rate limit (the quota is shared by every parallel session), fall back to REST via `gh api` for reading, commenting, closing, and merging with a pinned head SHA.

# Loops

- Follow the Workspace rules from `quest guide` in every repository (outside a quest repo, read [them on GitHub](https://github.com/kixelated/quest/blob/main/assets/AGENTS.md#workspace)): scratch in the checkout's `.tmp/`, checkpoints, a clean checkout at handoff, blocking waits, and sub-agents that end without background work.
- Preserve local-only submodule commits before releasing a worktree, and track the actual PR branch so cleanup can verify completion.
- Stay silent on notifications that change nothing.

# Shell

- In a worktree-isolated session, run git as its own plain command: no chaining, variables, or xargs.
- Read exit codes directly (`cmd > log 2>&1; echo EXIT=$?`), never through a pipe like `| tail`.

# Development

- Default to worktrees, except `~/work/dotfiles`: it is live config, so edit in place.
- Prefer the net simpler result: reuse what exists, or narrow the scope, when that makes the implementation or API simpler overall.
- Don't set arbitrary acceptance criteria.
