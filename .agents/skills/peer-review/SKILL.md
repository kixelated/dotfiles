---
name: peer-review
description: Launch Claude Code headlessly for an adversarial second-opinion review of the working tree or current branch. Use when the user invokes /peer-review, asks for Claude's take, or wants a review from a different model. Claude runs read-only; you triage its findings and fix only what you verify.
---

# Claude adversarial review

Get a different model's opinion without leaving the session or bouncing through GitHub. Launch Claude Code non-interactively with read-only tools; it inspects the diff and prints findings. You are the triage judge: verify every finding against the actual code before acting, fix what you agree with, and state why you reject the rest. Adversarial framing manufactures some objections by design.

## Scope

- Working tree: uncommitted work (`git status --short` shows changes).
- Branch: resolve the base first, e.g. `BASE=$(git merge-base HEAD origin/main)` (use the repo's actual target branch), and review `$BASE..HEAD`.

State the scope explicitly in the prompt; headless Claude only knows what you tell it. Append any user-supplied focus text.

## Run

Requires the `claude` CLI on PATH (`claude --version`). If it's missing, say so instead of substituting your own review. Reviews take minutes; use a generous command timeout or your background facility.

```bash
claude -p "You are an adversarial code reviewer in this repository. Review <SCOPE: the uncommitted changes | the commits BASE..HEAD, base = <sha>>. Challenge the approach, design, and assumptions, not just the implementation: is this the right shape, what does it silently depend on, where does it fail under real conditions? Read the surrounding code before judging. Report only findings you can defend, each as: file:line, severity (blocker/major/minor), the claim, and the concrete failure scenario. If nothing real turns up, say exactly that instead of inventing nitpicks. Focus: <focus or 'none'>." \
  --allowedTools "Read Grep Glob Bash(git diff:*) Bash(git log:*) Bash(git show:*) Bash(git status:*) Bash(git merge-base:*)" \
  --output-format text
```

The tool allowlist is the guardrail: Claude can read files and git history but cannot edit, commit, or run anything else. Keep it that way; never add write tools or `--dangerously-skip-permissions`.

## Afterwards

Return Claude's findings to the user, then triage: for each finding, check the cited code, and only then fix or rebut. Don't loop reviews more than once; a second full pass on an unchanged diff is noise.
