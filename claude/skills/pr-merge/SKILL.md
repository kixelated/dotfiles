---
name: pr-merge
description: Rebase, adversarially review (via Codex), and merge a GitHub PR once CI is green, backing out if anything questionable turns up. Use whenever the user wants to land, ship, finish, or merge a pull request — e.g. "review and merge PR 123", "land this once CI passes", or just "merge this PR". Codex (a second model) does the rebase and the final review; Claude triages, fixes agreed findings, gates on CI, and executes the merge. Prefer this over a bare `gh pr merge` so the PR is second-opinion-reviewed and CI-gated first.
argument-hint: "[pr-number] [optional review focus / instructions]"
---

# Merge PR

Land a pull request through a pipeline: rebase onto the fresh base (Codex), adversarial review + fixes (`/pr-review`, which also uses Codex), then a CI-gated merge (you). Codex carries the token-heavy work on the user's Codex subscription and serves as a second model's opinion; you stay the orchestrator and final judge, and you execute the merge — Codex's sandbox doesn't get to push the button.

Parse `$ARGUMENTS`: the first token (if numeric) is the PR number, and everything after it is extra instructions or review focus. If no PR number is given, resolve it from the current branch:
`gh pr list --head "$(git branch --show-current)" --json number --jq '.[0].number'`.

Locate the Codex runtime the same way `/pr-review` does:
```bash
COMPANION=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
node "$COMPANION" setup --json   # confirm "ready": true
```
If Codex isn't available, say so and ask whether to proceed with a Claude-only review (`/code-review`) instead — don't quietly drop the second opinion.

## Guardrails: back out when questionable

Merging is irreversible and outward-facing. Invoking this skill authorizes the merge for the clean happy path (rebase clean or trivial, no open review questions, CI green) — there, merge without re-asking; that is the whole point. Anywhere off that path, **back out**: undo any half-applied state (abort an in-progress rebase, disable auto-merge if you enabled it, don't push unverified work), leave the PR unmerged, and report what you found so the user decides. Back out when:

- The review surfaces an **ambiguous, architectural, breaking, or contestable** finding. Fix the unambiguous ones; never merge over the rest.
- A **rebase conflict** isn't mechanically obvious. A guessed conflict resolution that merges is worse than a stalled PR.
- **CI is failing** after your fixes, or a check can't be made green without a judgment call.
- The PR is **blocked** by branch protection (required reviews/approvals). Report it; don't try to bypass it.
- The diff does something the **PR description doesn't claim** — surprise scope is a human's call.

Never merge a draft, a closed PR, or one that is already merged.

## Steps

1. **Pre-flight** — gather state before touching anything:
   - `gh pr view <number> --json number,title,body,state,isDraft,mergeable,mergeStateStatus,baseRefName,headRefName,reviewDecision,reviews,additions,deletions,changedFiles,statusCheckRollup`
   - Not `OPEN`, or a draft → report and stop.
   - `<base>` everywhere below is the PR's `baseRefName` — never assume `main` (this repo also targets `dev`). Every rebase and Codex review below must run against the freshly fetched `origin/<baseRefName>`, or Codex reviews the two branches' entire divergence instead of the PR.
   - Note `reviewDecision` and `mergeStateStatus`. `BLOCKED` with required approvals missing means a human must approve before it can land — flag that now, not at the end.

2. **Worktree** — `git fetch origin`, then check the PR branch out in a worktree under `.claude/worktrees/` (`git worktree add "$WT" --detach origin/<base>; cd "$WT" && gh pr checkout <number>`). All edits go through the worktree's absolute path.

3. **Rebase via Codex** — if the branch is `BEHIND` or `DIRTY` against its base, delegate the rebase:
   ```bash
   cd "$WT" && node "$COMPANION" task --write "Rebase this branch onto origin/<base>. Resolve conflicts only where the resolution is mechanically obvious (pure moves, non-overlapping edits, lockfile regeneration). If any conflict requires a judgment call, run 'git rebase --abort' and report the conflicting files and why. Do not push, commit --amend unrelated work, or touch anything beyond the rebase."
   ```
   Run in the background (`run_in_background: true`) and wait for the notification. Then verify yourself: `git log`/`git diff origin/<base>...HEAD` should show only the PR's own commits, and the project checks must pass. Push with `git push --force-with-lease=<branch>:<old-head-sha>` (another session may be live on the branch — the lease catches that). If Codex aborted or the result looks off, back out and report. If the branch is already up to date, skip this step; don't rebase for sport, since a force-push restarts CI.

4. **Review** — decide whether a fresh review adds signal. Skip it if **either** holds:
   - **Small and low-risk**: docs, comments, a dependency bump, formatting, a localized one-liner — judge by risk, not just `additions`/`deletions` (a few lines of protocol/auth/wire logic still deserve the look; a big mechanical diff usually doesn't).
   - **Already reviewed and unchanged**: an existing substantive approval whose `submittedAt` postdates the head commit (`gh pr view <number> --json commits --jq '.commits[-1].committedDate'`).

   Otherwise, run the `/pr-review` skill against this PR (reuse the same worktree; pass along any user focus). It runs the Codex adversarial review, triages, applies agreed fixes, pushes, and files issues for out-of-scope findings. Its "ask first" bucket is binding here: any ambiguous/architectural/breaking finding means back out, summarize, and ask before merging.

   Reviewed or skipped, still sweep existing unresolved PR comments — they're findings regardless:
   - Inline: `gh api repos/{owner}/{repo}/pulls/<number>/comments --jq '.[] | {user: .user.login, path, line, body}'`
   - Issue-level: `gh api repos/{owner}/{repo}/issues/<number>/comments --jq '.[] | {user: .user.login, body}'`
   - Human comments are authoritative. AI reviewer comments (CodeRabbit, Copilot, Gemini, etc.) go through the same triage as Codex findings: verify each against the code, fix the ones you agree with, and record the rejected ones with reasons in your report. Don't merge with an agreed-with AI finding left unaddressed, and don't act on one you haven't verified.

   If you're unsure whether the change is small enough to skip the review, run it — that's the cheaper mistake.

5. **Re-check after substantive fixes** — if step 4 changed more than trivia, ask Codex for a cheap final pass over just the delta:
   ```bash
   cd "$WT" && node "$COMPANION" task --resume-last "Re-review only the commits added since your review. Confirm they address the findings without introducing new problems. Verdict: MERGE or HOLD, with reasons."
   ```
   A HOLD verdict you agree with means back out; a HOLD you disagree with goes to the user with both positions stated. Don't loop more than once — endless re-review is its own failure mode.

6. **Gate on CI, then merge** — merge only when required checks pass:
   - Green and mergeable → `gh pr merge <number> --squash`.
   - Checks still running → once Codex has given the OK (a clean review, or a MERGE verdict in step 5) and every finding is resolved, enable `gh pr merge <number> --squash --auto` right away so it lands the moment CI goes green (this survives the turn ending). Optionally watch `gh pr checks <number> --watch --fail-fast` in the background to catch a red check early and confirm it landed. Never enable `--auto` before Codex's OK or with an open question outstanding — auto-merge is a promise you can't take back.
   - Checks failed and you can't green them with a root-cause fix → back out and report. Don't merge, and don't paper over a red check with retries.
   - Prefer `--squash`. If the repo disallows it the command errors; fall back to whatever `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed` permits.

7. **Report** — summarize: rebase outcome, whether you reviewed or skipped (and why), findings and their fates (fixed / rejected with reason / issue-filed / escalated), CI outcome, and the merge result with the PR URL. If you enabled auto-merge rather than merging directly, say so explicitly. If anything was backed out, lead with that and what decision you need. For out-of-scope work that got filed as issues, offer to spawn a fresh session/worktree on the meatiest one — offer, don't launch unasked.
