---
name: peer-review
description: Run an adversarial Codex review of the working tree or current branch. Use when the user invokes /peer-review or wants Codex's second opinion on changes that aren't a PR yet. Review-only; returns Codex's findings verbatim and never fixes anything.
---

# Codex adversarial review

Run Codex's challenge review through the runtime vendored with these dotfiles. It questions the chosen approach, design, and assumptions, not just implementation defects. This skill is review-only: run the review and return Codex's output verbatim; do not fix, patch, or promise changes. For reviewing an open PR (with triage and fixes), use `/pr-review` instead.

Locate the runtime, preferring the vendored copy and falling back to the Claude plugin cache:

```bash
DOTFILES="$(realpath ~/.claude/skills/../..)"
COMPANION="$DOTFILES/vendor/codex-plugin-cc/plugins/codex/scripts/codex-companion.mjs"
[ -f "$COMPANION" ] || COMPANION=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
node "$COMPANION" setup --json   # confirm "ready": true
```

If neither exists or setup isn't ready, say so and offer `/code-review` as a Claude-only fallback; don't silently substitute yourself for the second opinion.

Then run it, passing `$ARGUMENTS` through unmodified (it supports `--wait`/`--background`, `--base <ref>`, `--scope auto|working-tree|branch`, and trailing focus text):

```bash
node "$COMPANION" adversarial-review $ARGUMENTS
```

Size the diff first (`git diff --shortstat`, or `git diff --shortstat <base>...HEAD` for branch scope). Unless the user passed `--wait` or `--background`, run tiny reviews (1-2 files) in the foreground and everything else as a background Bash call (`run_in_background: true`), telling the user the review is running; the result arrives as a task notification. Either way, return Codex's output exactly as-is.
