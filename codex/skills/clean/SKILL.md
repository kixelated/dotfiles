---
name: clean
description: Safely audit and reclaim disk space from stale Git worktrees, native build artifacts, compiler caches, container VM storage, and unreachable Nix paths. Use when the user invokes /clean or $clean, asks what is using disk space, wants stale Codex or Claude checkouts removed, requests cargo clean or equivalent cleanup across worktrees, needs kache or container-storage analysis, or wants cleanup without raw deletion.
---

# Clean disk space safely

Audit first, then reclaim only reproducible or proven-stale data with its owning tool. Treat every worktree whose removal safety is not proven as active or protected.

## Non-negotiable guardrails

- Never run `rm`, `rmdir`, `find -delete`, a trash command, or an equivalent raw recursive deletion.
- Never use `git worktree remove --force` or delete a main worktree.
- Never delete a branch as part of this workflow.
- Never remove a dirty, locked, unregistered, missing-but-unverified, or possibly active worktree.
- Never clean dependency directories such as `node_modules`, virtual environments, vendored sources, or package-manager caches by default. The final unreachable-path Nix GC is the deliberate exception.
- Never clean build output while a process has a working directory inside that checkout or a build using its target directory is running.
- Never purge an entire compiler cache, prune container volumes, reset or recreate a container VM, or uninstall an application unless the user explicitly authorizes that named action and its data-loss consequence.
- Never delete sparse VM disk images directly. Use the owning application's supported inspection, prune, compact, reset, or uninstall workflow.
- Treat an unavailable activity signal as uncertainty, not evidence of staleness.
- Preserve a target and report it whenever a check fails or disagrees with another check.

## 1. Inventory first

Read applicable `AGENTS.md` files and repository cleanup conventions before acting.

Use roots explicitly named by the user. Otherwise inventory the current checkout, `~/.codex/worktrees`, and existing `~/work/*/.claude/worktrees` containers. Run the bundled read-only helper from this skill directory:

```bash
python3 scripts/inventory_worktrees.py --sizes [ROOT ...]
```

The helper sets `GIT_OPTIONAL_LOCKS=0`, discovers registered worktrees, and reports Git state, upstream state, base reachability, ecosystems, and approximate size. Do not treat its output alone as permission to remove anything.

When the request concerns overall disk pressure or build/cache usage, also run:

```bash
python3 scripts/audit_disk_usage.py
```

This read-only helper reports filesystem capacity, high-value disk categories, Cargo target totals, and logical versus physically allocated sparse container disks. Use its measured sizes to prioritize native cleanup; do not infer safety from size.

Also collect active-use evidence:

- Mark the current task's checkout active.
- When task/thread tools are available, inspect non-completed Codex tasks and mark every referenced checkout active.
- Inspect process working directories with a read-only facility such as `lsof -n -a -d cwd`; mark matching worktrees active.
- Treat Git worktree locks as active/protected.
- If task or process evidence cannot be checked, require the user to confirm the proposed stale list before removal.

## 2. Classify conservatively

Assign every existing registered checkout exactly one category:

- **Active:** referenced by the current or another non-completed task, used as a process working directory, or explicitly identified as active by the user.
- **Stale eligible:** all of the following are true:
  - it is not the repository's main worktree;
  - it is within the requested cleanup scope;
  - it is registered, exists, and is unlocked;
  - Git status is clean, including untracked files;
  - no task or process activity signal applies;
  - a checked-out local branch is either merged into the detected local base or has a configured upstream reported as gone. Removing the worktree must leave that local branch intact;
  - for detached HEAD, the commit is reachable from a persistent local branch, remote-tracking branch, or tag, with no unique detached commit at risk.
- **Protected/unknown:** any worktree that does not satisfy every stale-eligible condition. Dirty worktrees always belong here even if their branch is merged.

Recency alone never proves staleness. An old modification time is supporting context only.

Present a compact action table before mutation with path, category, branch or detached HEAD, cleanliness, activity evidence, approximate size, and intended action. If the user's cleanup request already clearly authorizes removal of every stale-eligible target, continue. Pause for confirmation only when scope or activity remains uncertain.

## 3. Remove only stale-eligible worktrees

For each stale-eligible checkout, use a surviving worktree from the same repository:

```bash
git -C <surviving-worktree> worktree remove <absolute-stale-path>
```

Use an explicit absolute path and no force option. If Git refuses, preserve the checkout and report the exact reason; do not work around the refusal.

After removals, preview stale metadata cleanup:

```bash
git -C <surviving-worktree> worktree prune --dry-run --verbose --expire now
```

Run the same command without `--dry-run` only when every entry in the preview has been verified as already absent and unlocked; Git cannot prune a selected subset in one invocation. Otherwise preserve the metadata and report it. Leave unregistered orphan directories in place and report them.

## 4. Clean native build artifacts in retained worktrees

Classify worktree removal and build-artifact cleanup independently. Dirtiness, unmerged history, or detached reachability can protect a worktree from removal without protecting reproducible build output inside it.

A retained worktree is **artifact-clean eligible** when all of these are true:

- it is registered, exists, and is within the requested build-cleanup scope;
- no process working directory is at or beneath it, and no running build uses its target directory;
- the user requested build cleanup generally or authorized the presented cleanup list;
- a documented repository-wide clean command or applicable native command below is available and inspected.

A non-completed task reference alone does not block native cleanup when no process is using the checkout, but report that the task will need to rebuild. Process activity always blocks cleanup. Clean eligible worktrees serially, largest measured native artifact first. Measure before and after, and avoid cleaning the same shared target directory more than once.

Prefer a documented repository-wide clean command when it safely covers all languages. Inspect any repository-provided clean target before running it, especially if it shells out to raw deletion or expands variables into paths.

Use the applicable native command:

| Project evidence | Preferred command | Constraints |
| --- | --- | --- |
| `Cargo.toml` | `cargo clean` | Honor a documented toolchain or dev-shell wrapper. Use `cargo metadata --no-deps --format-version 1` when needed to identify shared target directories and avoid redundant cleans. |
| `package.json` | Detected package manager's `run clean` | Run only when an explicit `clean` script exists and its definition has been inspected. Never substitute deletion of `node_modules`, `dist`, or caches. |
| `Package.swift` | `swift package clean` | Use at the package root. |
| `gradlew` | `./gradlew clean` | Prefer the checked-in wrapper. |
| `mvnw` or `pom.xml` | `./mvnw clean` or `mvn clean` | Prefer the checked-in wrapper. |
| `.sln`, `.csproj`, or `.fsproj` | `dotnet clean` | Use the narrowest solution or project root. |
| `go.mod` | `go clean ./...` | Do not add global `-cache`, `-modcache`, or `-testcache` flags unless the user separately requests global cache cleanup. |
| Configured CMake build tree | `cmake --build <build-dir> --target clean` | Use only a verified configured build directory. |
| Bazel workspace | `bazel clean` | Never add `--expunge` by default. |
| `Makefile`, `justfile`, Python, or another system | Inspected documented clean target | Skip when no safe project-native target is documented; do not invent raw file deletion. |

Do not install missing tools or dependencies merely to clean. Record skipped ecosystems and the reason. Stop cleaning a worktree after a failed command unless a documented, equivalent safe command is evident.

## 5. Handle global caches and container storage

Global caches and VM storage cross repository boundaries. Audit them on every general disk-cleanup request, but mutate them only under the policies below.

### kache

- Measure `~/Library/Caches/kache` and run `kache stats` when `kache` is already installed.
- Inspect processes first. Skip mutation while `kache`, Cargo, Rust, or C/C++ builds are using the cache.
- If the user explicitly requests compiler-cache cleanup and supplies an age, run `kache gc --max-age <AGE>`.
- If no age policy is supplied and cleanup would be material, ask the user to choose: `30d` conservative (recommended), `7d` more space, or audit only.
- Never run `kache purge` by default. Report that eviction trades disk space for future recompilation.

### Podman and Docker

- Run `podman system df` or `docker system df` only when the tool and daemon are available.
- Compare engine-reported live objects with the sparse disk's physically allocated size from `audit_disk_usage.py`. A large difference is VM high-water space, not proof that the raw image is safe to delete.
- Treat image, build-cache, container, and volume cleanup as separate decisions. Never include volumes without explicit authorization.
- Do not reset, recreate, or compact a VM automatically. Present the live-object evidence, expected reclaim, and loss/re-download consequences first.
- If the user explicitly requests Docker Desktop uninstall on macOS, use `/Applications/Docker.app/Contents/MacOS/uninstall`, then verify both the app and its managed container data. If macOS reports `operation not permitted`, stop and report the protected path; do not use raw deletion as a fallback.

### Other application and tool data

Report large app-managed data such as Claude VM bundles, Android SDK/emulators, Rust toolchains, browser data, and general caches separately. Use the owning app or package manager only after the user selects that category. Do not classify app data as disposable merely because it is under a cache-named directory.

## 6. Garbage-collect the Nix store

Run Nix GC once at the end of every cleanup without asking for confirmation. This is global rather than worktree-scoped and may cause future development shells or builds to redownload paths, so report that consequence.

Before GC:

- Check that `nix` is already available. Do not install Nix or enter a dev shell merely to run GC.
- Inspect running processes. Ignore the resident `nix-daemon`, but if another user-facing Nix command, build, evaluation, shell, or develop session is active, skip GC and report the reason. Do not pause for input.
- Record available disk space, then run:

```bash
nix store gc
```

Do not run a separate dry-run and do not add `--max`; collect all currently unreachable store paths in one traversal. Do not run `nix-collect-garbage -d`, delete generations, remove profiles or GC roots, or use `nix store delete`. If GC fails, stop the Nix step, preserve the store, and report the exact error without trying a more destructive fallback.

## 7. Verify and report

Re-run both applicable helpers after cleanup. Report:

- stale worktrees removed and their branches, commits, and reclaimed sizes;
- artifact-cleaned worktrees, exact native commands, and measured reclaimed sizes;
- protected, ambiguous, or failed worktrees and why they were preserved;
- skipped build systems and missing tools;
- compiler-cache and container-storage actions or deliberate skips;
- Nix GC result and its reported or measured reclaimed space;
- approximate total space reclaimed, distinguishing worktree removal, native builds, global caches, container storage, applications, and Nix GC.

State explicitly that no raw removal command and no forced Git worktree removal was used.
