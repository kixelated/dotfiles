---
name: peer-review
description: Launch Claude Code headlessly for an adversarial second-opinion review of the working tree or current branch. Use when the user invokes /peer-review, asks for Claude's take, or wants a review from a different model. Claude runs read-only; you triage its findings and fix only what you verify.
---

Get a second opinion from Claude without leaving the session or bouncing through GitHub.
Claude proposes; you are the triage judge, so verify every finding against the actual code before acting on it. Adversarial framing manufactures some objections by design.

- Determine the scope. Working tree means the uncommitted changes (`git status --short`); branch means `$BASE..HEAD`, resolving the base first with `git merge-base HEAD origin/<target>` against the repo's actual target branch.
- State that scope explicitly in the prompt. Headless Claude only knows what you tell it. Append any focus text the user gave.
- Requires the `claude` CLI on PATH (`claude --version`). If it's missing, say so instead of substituting your own review.
- Reviews take minutes, so use a generous timeout or run it in the background.

```bash
claude -p "You are an adversarial code reviewer in this repository. Review <SCOPE: the uncommitted changes | the commits BASE..HEAD, base = <sha>>. Challenge the approach, design, and assumptions, not just the implementation: is this the right shape, what does it silently depend on, where does it fail under real conditions? Read the surrounding code before judging. Report only findings you can defend, each as: file:line, severity (blocker/major/minor), the claim, and the concrete failure scenario. If nothing real turns up, say exactly that instead of inventing nitpicks. Focus: <focus or 'none'>." \
  --allowedTools "Read Grep Glob Bash(git diff:*) Bash(git log:*) Bash(git show:*) Bash(git status:*) Bash(git merge-base:*)" \
  --output-format text
```

The tool allowlist is the guardrail: Claude can read files and git history but cannot edit, commit, or run anything else. Keep it that way, and never add write tools or `--dangerously-skip-permissions`.

Afterwards, return Claude's findings to the user, then triage each one against the cited code before you fix or rebut it. Don't loop reviews more than once; a second pass on an unchanged diff is noise.
