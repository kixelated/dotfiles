---
name: takeover
description: Adopt someone else's open PR and drive it to landable — judge whether the approach is right, make the changes you'd have made, get CI green, and address the review comments you agree with. Use when the user hands over a PR they didn't write (a contributor's, a bot's, an agent's, a stalled collaborator's) — e.g. "/takeover https://github.com/owner/repo/pull/123", "take over this PR", "finish this PR for me". Stops before merging.
---

# Take Over a PR

Someone else opened this PR; you are now responsible for it. Judge the approach first, then make it landable. Never merge — hand off to `/pr-merge`.

`$ARGUMENTS`: a PR URL or number, plus any extra instruction. No PR given → resolve from the current branch (`gh pr list --head "$(git branch --show-current)" --json number --jq '.[0].number'`). A URL pointing at a different repo than the one you're in → ask before going further.

1. **Read it**: `gh pr view <pr> --json title,body,state,isDraft,author,baseRefName,headRefName,isCrossRepository,maintainerCanModify,statusCheckRollup` and `gh pr diff <pr>`, plus the issue it claims to fix. Closed or merged → stop.

2. **Judge the approach** before touching anything, reading the surrounding code and this repo's conventions. If it's wrong-headed or shouldn't land at all, say so and stop — redesigning or closing someone's PR is the user's call. Otherwise state the verdict in a line and continue.

3. **Check it out** in a worktree under `.claude/worktrees/`: `git fetch origin && git worktree add "$WT" --detach origin/<base> && cd "$WT" && gh pr checkout <pr>`. `<base>` is the PR's `baseRefName`, never assumed. A fork PR with `maintainerCanModify: false` can't be pushed to — report that and ask.

4. **Fix**: the changes you'd have made (in this PR's scope — adjacent problems become issues), then the review comments you agree with. Verify each comment against the code first; human comments are authoritative, AI reviewers get no deference. Note the ones you reject and why. For a substantive diff, run `/pr-review` for a second opinion before settling the list.

5. **Push**: run the project's checks locally (`nix develop --command just fix`, `just check`, or the equivalent), re-fetch, then `git push origin HEAD:<headRefName>`.

6. **Green the CI**: read failures (`gh run view <run-id> --log-failed`) and fix the root cause. Failures that also fail on `origin/<base>` are pre-existing — say so and leave them. If a check needs a judgment call to go green, stop and report.

7. **Report**, and reply on GitHub to the comments you acted on or rejected — every post ending with `(written by <the running model>)`, and nothing posted outside `kixelated/moq-dev` without approval. Offer `/pr-merge`.

## Rules

- Never merge, approve, or close the PR. Taking it over makes you its author, not its reviewer.
- Keep the author's credit: their commits stay theirs, yours go on top, never reauthored or force-pushed away.
- Never green a check by weakening it — no skipped tests, deleted assertions, or loosened lint.
