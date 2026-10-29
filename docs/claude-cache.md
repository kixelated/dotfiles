# Claude prompt cache policy

Run `python3 bin/install-claude-cache.py` to apply the policy without running the
full dotfiles installer. The installer also runs it automatically. It merges
these two settings into each profile while preserving plugins, hooks, model
settings, and other local configuration:

| Profile | Main conversation | Subagents |
| --- | --- | --- |
| `~/.claude` | `1h` | `1h` |
| `~/.claude-personal` | `1h` | `1h` |
| `~/.claude-api-credits` | `1h` | `1h` |

Each `CLAUDE_CONFIG_DIR` has its own settings file. The personal and API-credit
profiles do not inherit the default profile's cache settings. This also covers
T3 providers that invoke the Claude binary directly instead of using a wrapper.
Start a new Claude process after applying the policy.

The October 2026 audit found repeated cache rebuilds after five-minute waits.
All profiles use one-hour caches to retain large contexts through waits and
resumed work, including API-credit subagents. This keeps the policy consistent
across providers.

At current API prices, one-hour writes cost 2x base input versus 1.25x for
five-minute writes. Hits refresh the lifetime, so continuous work within five
minutes does not benefit from the longer TTL. Subscription limits use separate
metering; API-equivalent savings are not invoice or quota savings.

See [Claude Code's cache controls](https://code.claude.com/docs/en/prompt-caching)
and [API cache pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
Environment overrides, especially `FORCE_PROMPT_CACHING_5M` and the two
`CLAUDE_CODE_*PROMPT_CACHE_TTL` variables, take precedence over these settings.
