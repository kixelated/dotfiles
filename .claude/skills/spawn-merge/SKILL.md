---
name: spawn_merge
description: Land multiple GitHub PRs once reviews and CI pass.
---

Land multiple pull requests.
For each PR, run /spawn using a sub-agent in its own worktree.
Limit the maximum concurrency to half of the physical CPU cores.

This agent will continue until the PR is merged or it encounters an issue.
Interactively prompt the user to resolve issues.

Summarize the results when done.
