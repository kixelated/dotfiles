---
name: pr-review
description: Adversarial second-opinion review of a GitHub PR using Codex (a different model), then triage and fix the findings Claude agrees with. Use when the user wants a PR reviewed with a second opinion — e.g. "pr-review 123", "get codex's take on this PR", "adversarial review this branch and fix what's real". Runs the Codex plugin's adversarial review against the PR branch in a worktree, verifies each finding against the code, applies the agreed fixes, pushes, and files GitHub issues for real-but-out-of-scope problems. Never merges.
---

# Adversarial PR Review (Codex second opinion)

Offload the heavy review pass to Codex so it burns the user's Codex subscription instead of Claude tokens, and so a *different model* challenges the change. Codex proposes; you are the triage judge. Verify every finding against the actual code before acting on it, fix what you agree with, and defend (in your report) what you reject. This skill never merges — that's `/pr-merge`.

Parse `$ARGUMENTS`: first token (if numeric) is the PR number; the rest is review focus. No PR number → resolve from the current branch: `gh pr list --head "$(git branch --show-current)" --json number --jq '.[0].number'`.

## Locate the Codex runtime

The plugin's slash commands can't be model-invoked, but they are thin wrappers over a companion script you can call directly:

```bash
COMPANION=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
node "$COMPANION" setup --json   # confirm "ready": true
```

If the script is missing or setup reports not ready, tell the user (point them at `/plugin` install or `/codex:setup`) and offer to fall back to the `/code-review` skill instead. Don't silently substitute yourself for Codex — the whole point is the second opinion.

## Steps

1. **Resolve and inspect the PR**:
   `gh pr view <number> --json number,title,body,state,isDraft,baseRefName,headRefName,additions,deletions,changedFiles`
   `<base>` everywhere below is the PR's `baseRefName` — never assume `main`. Repos here target both `main` and `dev`, and reviewing against the wrong base makes Codex review every commit the branches differ by, drowning the real diff in someone else's work.

2. **Check out the PR in a worktree** so the user's checkout is untouched:
   ```bash
   git fetch origin
   git worktree add "$WT" --detach origin/<base>
   cd "$WT" && gh pr checkout <number>
   ```
   Use a path under the repo's `.claude/worktrees/` (e.g. `pr-<number>-review-<suffix>`). Always edit files by the worktree's absolute path.

3. **Run the adversarial review**. Build a short focus string: the PR title, a one-line statement of what the PR claims to do, plus any user-supplied focus. Then, from the worktree:
   ```bash
   cd "$WT" && node "$COMPANION" adversarial-review --wait --base origin/<base> --scope branch "<focus>"
   ```
   `--base` must be the freshly fetched `origin/<baseRefName>` from step 1. Sanity-check before launching: `git rev-list --count origin/<base>..HEAD` should be roughly the PR's own commit count; a suspiciously large number means the base is wrong or stale — fix that first, don't review a polluted diff. Run this Bash call with `run_in_background: true` (reviews can take several minutes; the notification arrives when it finishes). Don't poll — do nothing or other prep while it runs. If the run fails, surface the actionable stderr; if Codex never ran at all, fall back to `/code-review` and say so.

4. **Triage every finding** — Codex's, plus any unresolved review comments already sitting on the PR:
   - Inline: `gh api repos/{owner}/{repo}/pulls/<number>/comments --jq '.[] | {user: .user.login, path, line, body}'`
   - Issue-level: `gh api repos/{owner}/{repo}/issues/<number>/comments --jq '.[] | {user: .user.login, body}'`
   Human comments are authoritative. AI reviewer comments (CodeRabbit, Copilot, Gemini, etc.) get the same verify-first treatment as Codex's. Sort everything into three buckets, reading the cited code before bucketing — findings are advisory, not authoritative, and adversarial framing produces some manufactured objections by design:
   - **Agree**: you verified it's a real defect or a clear improvement within this PR's scope.
   - **Reject**: false positive, stylistic disagreement, or contradicts this repo's conventions (CLAUDE.md wins). Record *why* for the report — a rejected second opinion deserves a stated reason, not silence.
   - **Out of scope**: real, but pre-existing or beyond this PR (architecture concerns, adjacent bugs, missing features).

5. **Fix the agreed findings**:
   - Small/localized fixes: edit directly.
   - Substantive or mechanical-across-files fixes: delegate back to Codex to keep tokens on that side:
     ```bash
     cd "$WT" && node "$COMPANION" task --write --resume-last "Apply these fixes from your review: <numbered list>. Touch nothing else. Do not commit or push."
     ```
     (`--resume-last` keeps the review thread's context; if it errors, run a fresh `task --write` with the findings restated.) Then read the resulting `git diff` yourself — you own everything that gets pushed, regardless of who typed it.

6. **Verify and push**: run the project's checks from the worktree (`nix develop --command just fix` then `just check` in repos that have them; otherwise the project's equivalent). Re-fetch before pushing (another session may be live on the branch); push with `git push origin HEAD`, or `--force-with-lease=<branch>:<old-sha>` only if history was rewritten.

7. **File issues for out-of-scope findings** that are clearly real. First check for an existing one (`gh issue list --search "<keywords>"`); then one issue per distinct problem, referencing the PR and the finding, body ending with `(written by <the running model>)`. Skip anything speculative — an issue tracker full of "Codex wondered whether..." is noise.

8. **Report**: findings by bucket (fixed / rejected-with-reason / issue-filed), what was pushed, check results, and links to any issues. Offer, but don't do unasked:
   - posting the summary as a PR comment (with the `(written by ...)` attribution),
   - spawning a separate session/worktree to tackle a filed issue that's worth immediate work.

## Rules

- Never merge, approve, or close the PR from this skill.
- Never apply a Codex-suggested fix you haven't verified against the code.
- If a finding is ambiguous, architectural, or breaking, don't fix it on your own judgment — put it in the report and ask.
- Every GitHub post (issue, comment) ends with `(written by <the running model>)`.
