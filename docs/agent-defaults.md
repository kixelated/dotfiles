# Agent defaults

`./install` runs `python3 bin/install-agent-defaults.py`, which can also run on
its own. It sets each host's default model and reasoning effort, preserving
every other setting:

| Agent | Setting | Value |
| --- | --- | --- |
| Claude Code | `effortLevel` in `settings.json` of `~/.claude`, `~/.claude-personal`, and `~/.claude-api-credits` | `high` |
| Codex | `model` and `model_reasoning_effort` in `$CODEX_HOME/config.toml` | `gpt-6.1-sol`, `xhigh` |

Codex writes `config.toml` itself through `codex app-server`, so trust hashes and
other local keys survive. Without `codex` on `PATH`, the Codex part is skipped.

The installer resets these keys on every run, so change a default here rather
than with `/effort` or `/model`, which only last until the next install.
