---
name: peer-review
description: Run an adversarial Codex review of the working tree or current branch. Use when the user invokes /peer-review or wants Codex's second opinion on changes that aren't a PR yet. Review-only; returns Codex's findings verbatim and never fixes anything.
---

Get a second opinion from Codex, which challenges the approach, design, and assumptions rather than just the implementation.
This skill is review-only: return Codex's output verbatim, and never fix, patch, or promise changes.

Locate the runtime, preferring the copy vendored with these dotfiles and falling back to the plugin cache:

```bash
DOTFILES="$(realpath ~/.claude/skills/../..)"
COMPANION="$DOTFILES/vendor/codex-plugin-cc/plugins/codex/scripts/codex-companion.mjs"
[ -f "$COMPANION" ] || COMPANION=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
node "$COMPANION" setup --json   # confirm "ready": true
```

If neither exists or setup isn't ready, say so and offer `/code-review` as a Claude-only fallback. Don't silently substitute yourself for the second opinion.

Then run it, passing the arguments through unmodified. It supports `--wait`/`--background`, `--base <ref>`, `--scope auto|working-tree|branch`, and trailing focus text:

```bash
node "$COMPANION" adversarial-review $ARGUMENTS
```

Size the diff first (`git diff --shortstat`, or `git diff --shortstat <base>...HEAD` for branch scope). Unless the user passed `--wait` or `--background`, run tiny reviews of one or two files in the foreground and everything else in the background, telling the user the review is running; the result arrives as a notification. Either way, return Codex's output exactly as-is.
