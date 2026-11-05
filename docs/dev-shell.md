# Agent dev shells

Agents never have to care about Nix. Every Claude Code, Codex, and Grok
session loads the checkout's direnv dev shell into its commands through a
user-level `SessionStart` hook, so repositories need no checked-in hooks to
force direnv or Nix on contributors.

`./install` runs `python3 bin/install-dev-shell.py`, which can also run on its
own. It is idempotent and preserves every other setting and hook:

| Agent | Hook | How commands get the environment |
| --- | --- | --- |
| Claude Code | `SessionStart` in `settings.json` of `~/.claude`, `~/.claude-personal`, and `~/.claude-api-credits` | `$CLAUDE_ENV_FILE` sources a sidecar snapshot |
| Codex | `SessionStart` in `$CODEX_HOME/hooks.json`, trusted in `config.toml` | `shell_environment_policy.set.BASH_ENV` sources `codex/bash-env.sh`, which loads `<checkout>/.direnv/codex-env.sh` |
| Grok | `SessionStart` in `$GROK_HOME/hooks/dev-shell.json` | `session.load_envrc` runs `direnv export`, and `shell_environment_policy.set.BASH_ENV` sources `grok/bash-env.sh`, which loads `<checkout>/.direnv/grok-env.sh` |

Codex runs a user hook only after its declaration hash is recorded as trusted.
The installer asks `codex app-server` for that hash, so it stays correct across
Codex versions. Rerun the installer after editing the hook command. Without
`codex` on `PATH`, it installs the hook but skips trust and `BASH_ENV`.

## What the hook does

`bin/dev-shell-hook` does nothing without direnv or an `.envrc` at
`$CLAUDE_PROJECT_DIR` (Claude) or the Git checkout root (Codex and Grok).
Otherwise it runs `direnv exec` and writes only what the dev shell changes
relative to the agent's environment. Variables an agent filters out of its
commands, such as Codex's default secret exclusions, are therefore never
re-exported.

direnv keys each approval by the `.envrc` path and contents, so every new
worktree needs one. The hook runs `direnv allow` itself only when both hold:

- `HEAD` is contained in some last-fetched `origin` branch
  (`git for-each-ref --contains HEAD refs/remotes/origin/`). A session rooted
  at an outside contributor's fork PR head or at an unpushed local commit is
  therefore never auto-approved, even when its files match.
- `.envrc`, `flake.nix`, and `flake.lock` match the last-fetched remote default
  branch (`origin/HEAD`).

It never fetches, and it never whitelists directories. A HEAD off every origin
branch, a changed file, a missing `origin/HEAD`, or a `direnv deny` leaves the
checkout unapproved. The hook then exits 1 with one stderr line asking for
`direnv allow`. A checkout that is already approved keeps loading after new
local commits, because direnv's approval does not depend on `HEAD`.

Files that `.envrc` sources, or that `flake.nix` imports, are not compared.
Changing only those keeps the existing approval, as plain direnv would.

## Repositories with their own hooks

Some moq-dev repositories still ship `.claude/hooks/direnv.sh` or
`.codex/hooks/direnv.sh` until a later change removes them. The user hook still
runs there, and the double load is harmless:

- Claude Code gives each `SessionStart` hook its own `$CLAUDE_ENV_FILE`, so each
  hook writes its own sidecar. Both snapshots come from the same `.envrc`, and
  sourcing them in sequence produces the same environment. Hooks run in
  parallel, so skipping the user hook could not cover a project hook that fails.
  For example, quest's hook does not approve new worktrees. In a fresh worktree,
  quest's hook logs a `SessionStart` error while the user hook approves and
  loads the dev shell. The session still gets the environment.
- Codex hooks write the same `.direnv/codex-env.sh` atomically, and either
  snapshot is valid. Codex keys project hook trust by the `hooks.json` path, so
  project hooks in a fresh worktree are untrusted and only the user hook runs.
- Grok also reads Claude settings, so a repository `.claude/hooks/direnv.sh`
  runs there too. That script exports through `$CLAUDE_ENV_FILE`, which Grok
  does not set, so it leaves the environment alone. The user hook is the one
  that loads the dev shell.

The cost is one extra cached direnv evaluation per session start while both
hooks exist.

## New hosts

```sh
git -C ~/work/dotfiles pull
python3 ~/work/dotfiles/bin/install-dev-shell.py
```

Start a new Claude Code, Codex, or Grok session afterwards. A session that is
already running keeps the environment it captured at start.
