# Agent defaults

`./install` runs `python3 bin/install-agent-defaults.py`, which can also run on
its own. It sets each host's default model and reasoning effort, preserving
every other setting:

| Agent | Setting | Value |
| --- | --- | --- |
| Claude Code | `effortLevel` in `settings.json` of `~/.claude`, `~/.claude-personal`, and `~/.claude-api-credits` | `high` |
| Claude Code | `modelSettings.claude-opus-5-5.autoCompactWindow` in the same files | `400000` |
| Claude Code | `env.BASH_MAX_TIMEOUT_MS` in the same files | `3300000` |
| Codex | `model` and `model_reasoning_effort` in `$CODEX_HOME/config.toml` | `gpt-6.1-sol`, `xhigh` |
| Codex | `model_auto_compact_token_limit` in the same file | `240000` |

Codex writes `config.toml` itself through `codex app-server`, so trust hashes and
other local keys survive. Without `codex` on `PATH`, the Codex part is skipped.

The auto-compact window keeps Opus sessions from replaying close to a million
tokens a turn before compacting. The Bash cap lets a wait block for up to 55
minutes, just under the 1h prompt-cache TTL, and lives in settings rather than
the shell profile because sessions T3 Code starts never read one.

The installer resets these keys on every run, so change a default here rather
than with `/effort` or `/model`, which only last until the next install.
