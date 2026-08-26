---
name: clean
description: Audit disk usage and safely reclaim space from stale Git worktrees, build artifacts, compiler caches, container storage, and the Nix store. Use when the user invokes /clean, asks what is eating disk space, or wants stale worktrees or build output cleaned up.
---

# Clean disk space safely

Audit first; delete only reproducible artifacts and proven-stale worktrees, always through the owning tool. When in doubt, keep it and say why.

## Guardrails

- No raw deletion, ever: no `rm`, `find -delete`, trash commands, or `git worktree remove --force`. No deleting branches.
- Never remove a worktree that is dirty (untracked files count), locked, the main worktree, possibly in use, or whose commits are not reachable from some surviving ref.
- Never touch dependency dirs (`node_modules`, venvs, vendored sources) or purge a whole cache, volume, or container VM unless the user explicitly names that action.
- A missing activity signal means "assume active". A failed or contradictory check means preserve and report.

## Audit

Run the bundled read-only helpers (paths relative to this skill's directory):

```bash
python3 scripts/inventory_worktrees.py --sizes [ROOT ...]   # worktrees: git state, upstream, base reachability, sizes
python3 scripts/audit_disk_usage.py                         # disk categories, cargo targets, sparse VM disks
```

Default roots: the current checkout, `~/.codex/worktrees`, and `~/work/*/.claude/worktrees`. Then gather activity evidence: the current task's checkout, other live agent tasks, process working directories (`lsof -n -a -d cwd`), and git worktree locks.

## Remove stale worktrees

A worktree is removable only when all of these hold: registered, unlocked, not the main worktree, clean including untracked files, no activity signal, and its branch is merged into the base or its upstream is gone (for detached HEAD: the commit is reachable from a branch or tag). Everything else is protected. Recency alone proves nothing.

Show a short table (path, branch, state, size, intended action) before mutating; pause for confirmation only if scope or activity is uncertain. Remove with `git -C <surviving-worktree> worktree remove <abs-path>`, no force; if git refuses, keep it and report the reason. Afterwards run `git worktree prune --dry-run --verbose` and prune for real only when every listed entry is verifiably gone and unlocked.

## Clean build artifacts

Reproducible build output in a *retained* worktree can be cleaned even when the worktree itself is protected, as long as no process is running in or building from that checkout. Use the project's native clean command, largest target first, measuring before and after: `cargo clean`, `./gradlew clean`, `swift package clean`, `go clean ./...`, `dotnet clean`, `cmake --build <dir> --target clean`, `bazel clean` (never `--expunge`), or a documented repo-level clean recipe whose definition you have inspected. No safe native command means skip and report; never substitute raw deletion, and don't install tools just to clean.

## Caches and container storage

Audit and report sizes on every general cleanup; mutate only what the user explicitly requests:

- **kache**: measure `~/Library/Caches/kache` and run `kache stats`. Only gc when the user picks an age (`kache gc --max-age 30d` is the conservative recommendation). Never `kache purge` by default; note that eviction trades disk for recompilation.
- **Podman/Docker**: `podman system df` / `docker system df`. Compare live objects against the sparse disk's physically allocated size; the gap is VM high-water space, not something deletion reclaims. Images, build cache, containers, and volumes are separate decisions; never volumes, VM resets, or app uninstalls without explicit authorization.
- Report other large app-managed data (Android SDK, rustup, browser data) separately and act only on a category the user picks, via the owning app or package manager.

## Nix GC

Finish every cleanup with `nix store gc`, no confirmation needed, when `nix` is already installed and no other nix build/shell/develop session is running (the resident `nix-daemon` doesn't count). Don't install nix for this, don't use `nix-collect-garbage -d` or delete generations/profiles/GC roots, and report that collected paths may be re-downloaded by future builds.

## Report

Total reclaimed by category (worktrees, builds, caches, containers, nix), exact commands used, what was preserved or skipped and why, and any failures verbatim.
