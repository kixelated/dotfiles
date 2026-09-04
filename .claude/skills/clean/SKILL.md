---
name: clean
description: Audit disk usage and safely reclaim space from stale Git worktrees, build artifacts, compiler caches, container storage, and the Nix store. Use when the user invokes /clean, asks what is eating disk space, or wants stale worktrees or build output cleaned up.
---

Audit first, then delete only reproducible artifacts and proven-stale worktrees, always through the owning tool.
If unsure about any course of action, keep it, and say why.

## Guardrails

- Never delete by hand: no `rm`, `find -delete`, trash commands, or `git worktree remove --force`. Never delete branches.
- Never touch dependency dirs (`node_modules`, venvs, vendored sources), and never purge a whole cache, volume, or container VM unless the user names that action.
- A missing activity signal means "assume active". A failed or contradictory check means preserve and report.

## Audit

Run the bundled read-only helpers, relative to this skill's directory:

```bash
python3 scripts/inventory_worktrees.py --sizes [ROOT ...]   # worktrees: git state, upstream, base reachability, sizes
python3 scripts/audit_disk_usage.py                         # disk categories, cargo targets, sparse VM disks
```

Default roots are the current checkout, `~/.codex/worktrees`, and `~/work/*/.claude/worktrees`. Then gather activity evidence: this task's checkout, other live agent tasks, process working directories (`lsof -n -a -d cwd`), and git worktree locks.

## Worktrees

A worktree is removable only when it is registered, unlocked, not the main worktree, clean including untracked files, has no activity signal, and its branch is merged into the base or its upstream is gone (for detached HEAD, its commit is reachable from a branch or tag). Everything else is protected; recency alone proves nothing.

Show a table (path, branch, state, size, intended action) before mutating, and pause for confirmation if scope or activity is uncertain. Remove with `git -C <surviving-worktree> worktree remove <abs-path>`, no force; if git refuses, keep it and report why. Then `git worktree prune --dry-run --verbose`, pruning for real only when every listed entry is verifiably gone.

## Build artifacts

Build output in a *retained* worktree can still be cleaned, as long as no process is running in or building from that checkout. Use the project's own clean command, largest target first, measuring before and after: `cargo clean`, `./gradlew clean`, `swift package clean`, `go clean ./...`, `dotnet clean`, `cmake --build <dir> --target clean`, `bazel clean` (never `--expunge`), or a repo-level recipe whose definition you have read. No safe native command means skip and report; never substitute raw deletion, and don't install tools just to clean.

## Caches and containers

Report sizes on every cleanup, but mutate only what the user asks for:

- **kache**: measure `~/Library/Caches/kache` and run `kache stats`. Only gc once the user picks an age (`kache gc --max-age 30d` is the conservative recommendation). Never `kache purge` by default; eviction trades disk for recompilation.
- **Podman/Docker**: `podman system df` / `docker system df`. Compare live objects against the sparse disk's allocated size; the gap is VM high-water space that deletion won't reclaim. Images, build cache, containers, and volumes are separate decisions.
- Report other large app-managed data (Android SDK, rustup, browser data) separately, and act only through the owning app or package manager.

## Nix

Finish with `nix store gc`, no confirmation needed, when `nix` is already installed and no other nix build/shell/develop session is running (the resident `nix-daemon` doesn't count). Don't install nix for this, don't use `nix-collect-garbage -d`, and don't delete generations, profiles, or GC roots. Note that collected paths may be re-downloaded by future builds.

## Report

Total reclaimed by category, the exact commands used, what was preserved or skipped and why, and any failures verbatim.
