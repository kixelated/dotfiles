#!/usr/bin/env python3
"""Retire inactive Git worktrees through Git and MBX, never by raw deletion."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys


class Preserve(RuntimeError):
    pass


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.PIPE
    )


def text(root, *args):
    return os.fsdecode(git(root, *args)).strip()


def processes():
    if sys.platform.startswith("linux") and Path(
        "/proc/1/comm"
    ).read_text().strip() not in {"systemd", "init"}:
        raise Preserve("process namespace is restricted; run cleanup on the host")
    result = subprocess.run(
        ["lsof", "-n", "-P", "-a", "-u", str(os.getuid()), "-Fpn"],
        capture_output=True,
        cwd="/",  # The inspector itself must not look like checkout activity.
        text=True,
    )
    if result.returncode or not result.stdout:
        raise Preserve(f"cannot inspect activity: {result.stderr.strip()}")
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("n/"):
            paths.append(Path(line[1:].removesuffix(" (deleted)")))
    return paths


def idle(paths):
    for active in processes():
        if any(active == path or path in active.parents for path in paths):
            raise Preserve(f"active process uses {active}")


def worktrees(repo):
    record = {}
    for field in git(repo, "worktree", "list", "--porcelain", "-z").split(b"\0"):
        if not field:
            if record:
                yield record
                record = {}
        else:
            key, _, value = os.fsdecode(field).partition(" ")
            record[key] = value


def modules(repo):
    result = git(
        repo, "submodule", "foreach", "--quiet", "--recursive", 'printf "%s\\0" "$PWD"'
    )
    for path in result.split(b"\0"):
        if path:
            child = Path(os.fsdecode(path)).resolve()
            if repo not in child.parents:
                raise Preserve(f"submodule escapes checkout: {child}")
            yield child


# Ignored local state is still user data. Only these reproducible directories
# may accompany a clean checkout into removal.
ARTIFACTS = {
    "target",
    "node_modules",
    "dist",
    "build",
    ".svelte-kit",
    ".direnv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    # wrangler regenerates both; `just clean` in moq.pro sweeps them too.
    ".wrangler",
    "worker-configuration.d.ts",
    ".terraform",
    # moq.pro: downloaded demo media and the playwright dev-login state.
    "media",
    ".auth",
    "test-results",
}


def clean(repo):
    if any(
        line[:1].islower() or line.startswith(b"S ")
        for line in git(repo, "ls-files", "-v").splitlines()
    ):
        raise Preserve(f"index hides file changes in {repo}")
    if git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    ):
        raise Preserve(f"dirty or untracked files in {repo}")


def check_local_data(repo):
    for raw in git(
        repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"
    ).split(b"\0"):
        if raw:
            path = Path(os.fsdecode(raw))
            if not (
                set(path.parts[:-1]) & ARTIFACTS
                or path.name in ARTIFACTS
                or path.suffix == ".tsbuildinfo"
            ):
                raise Preserve(f"ignored local data: {repo / path}")


def eligible(repo, entry):
    wt = Path(entry["worktree"])
    if "locked" in entry or "prunable" in entry or not wt.is_dir():
        raise Preserve("locked, missing or prunable")
    if wt.is_symlink() or wt.resolve() != wt:
        raise Preserve("noncanonical worktree path")
    clean(wt)
    head = text(wt, "rev-parse", "HEAD")
    if "branch" not in entry:
        if not text(
            repo, "for-each-ref", f"--contains={head}", "refs/heads", "refs/tags"
        ):
            raise Preserve("detached commit has no surviving local branch or tag")
    else:
        merged = False
        for ref in (
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/main",
            "refs/remotes/origin/master",
        ):
            refs = text(repo, "for-each-ref", "--format=%(refname)", ref).splitlines()
            if not refs:
                continue
            result = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", head, ref],
                capture_output=True,
            )
            if result.returncode not in (0, 1):
                raise Preserve("cannot inspect merge ancestry")
            merged = result.returncode == 0
            break
        if not merged:
            upstream = text(
                repo, "for-each-ref", "--format=%(upstream)", entry["branch"]
            )
            if not upstream.startswith("refs/remotes/"):
                raise Preserve("unmerged branch without a remote upstream")
            if text(repo, "for-each-ref", "--format=%(refname)", upstream):
                raise Preserve("unmerged branch with an existing upstream")
    repos = [wt, *modules(wt)]
    for module in repos[1:]:
        clean(module)
        # Its gitdir dies with the worktree. Preserve every local/ref/reflog
        # commit absent from remote-tracking history, not merely current HEAD.
        if git(module, "rev-list", "--all", "--reflog", "HEAD", "--not", "--remotes"):
            raise Preserve(f"submodule contains local-only commits: {module}")
        if text(module, "stash", "list"):
            raise Preserve(f"submodule stash: {module}")
    protected = repos + [(root / "target").resolve() for root in repos]
    idle(protected)
    return repos


def execute(args, dry):
    print("  " + " ".join(map(str, args)), flush=True)
    if not dry:
        subprocess.run(list(map(str, args)), check=True)


def builders_idle():
    store = Path(
        subprocess.check_output(["mbx", "cache", "dir"], text=True).strip()
    ).resolve()
    idle([store.parent / "targets"])
    # MBX's global GC can touch stale managed targets outside a checkout.
    names = subprocess.check_output(
        ["ps", "-u", str(os.getuid()), "-o", "comm="], text=True
    ).split()
    if set(names) & {"cargo", "rustc", "rustdoc", "mbx", "nix", "nix-build"}:
        raise Preserve("a build/cache process is active")


def workspace_targets(root):
    store = Path(
        subprocess.check_output(["mbx", "cache", "dir"], text=True).strip()
    ).resolve()
    targets = store.parent / "targets"
    found = {}
    if not targets.exists():
        return found
    for version in targets.iterdir():
        if version.name != "v1" or not version.is_dir():
            raise Preserve(f"unsupported MBX target layout: {version}")
        for metadata in version.glob("*.json"):
            record = json.loads(metadata.read_text())
            if record.get("version") != 1 or not isinstance(
                record.get("workspace_root"), str
            ):
                raise Preserve(f"unsupported MBX target record: {metadata}")
            workspace = Path(record["workspace_root"])
            if workspace == root or root in workspace.parents:
                found.setdefault(workspace, []).append(
                    metadata.with_suffix("").resolve()
                )
    return found


def retire(repo, entry, dry):
    wt = Path(entry["worktree"])
    repos = eligible(repo, entry)
    # Refresh the lock and status after the audit, before releasing cache claims.
    fresh = next(item for item in worktrees(repo) if item["worktree"] == str(wt))
    if fresh != entry:
        raise Preserve("worktree registration changed during audit")
    eligible(repo, fresh)
    targets = workspace_targets(wt)
    idle([wt, *(target for paths in targets.values() for target in paths)])
    # MBX accepts a workspace path, including one with no recorded claim.
    for root in sorted(
        set(repos) | set(targets), key=lambda path: len(path.parts), reverse=True
    ):
        idle([wt, *targets.get(root, []), (root / "target").resolve()])
        execute(["mbx", "cache", "remove", root], dry)
    eligible(repo, fresh)
    # A completed checkout can retain local databases or ignored drafts. Release
    # its disposable managed targets, but preserve the checkout and that data.
    for root in repos:
        check_local_data(root)
    # Do not deinit: it mutates shared submodule configuration. Git owns removal
    # of the worktree and its per-worktree module metadata. One force only.
    has_modules = any(
        line.startswith(b"160000 ")
        for line in git(wt, "ls-files", "--stage").splitlines()
    )
    command = ["git", "-C", repo, "worktree", "remove"]
    if has_modules:
        command.append("--force")
    execute([*command, wt], dry)


def repositories(roots):
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for directory, dirs, files in os.walk(root):
            path = Path(directory)
            if ".git" in dirs or ".git" in files:
                try:
                    common = text(
                        path, "rev-parse", "--path-format=absolute", "--git-common-dir"
                    )
                except subprocess.CalledProcessError:
                    # A stray .git (an empty dir, a broken gitfile) is not a
                    # repository; skip it rather than abort the whole sweep.
                    print(f"skip: {path}: not a git repository", flush=True)
                    continue
                if common not in seen:
                    seen.add(common)
                    yield path
                dirs.clear()
            elif len(path.relative_to(root).parts) >= 4:
                dirs.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("--root", action="append", type=Path)
    parser.add_argument(
        "--gc", action="store_true", help="also run MBX GC with a 25GiB object budget"
    )
    args = parser.parse_args()
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    os.environ.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/cleanup-{os.getuid()}"))
    runtime.mkdir(mode=0o700, exist_ok=True)
    with (runtime / "worktree-clean.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("cleanup already running")
            return
        processes()  # Never interpret a sandbox's partial view as inactivity.
        failures = False
        roots = args.root or [
            Path.home() / "work",
            Path.home() / ".codex/worktrees",
            Path("/tmp"),
        ]
        for repo in repositories([root.resolve() for root in roots]):
            entries = list(worktrees(repo))
            if len(entries) > 1 and "origin" in text(repo, "remote").splitlines():
                # A deleted GitHub branch remains a local remote-tracking ref
                # until pruning. Refresh before treating the branch as finished.
                try:
                    execute(
                        [
                            "git",
                            "-C",
                            repo,
                            "-c",
                            "credential.interactive=false",
                            "fetch",
                            "--prune",
                            "--no-recurse-submodules",
                            "origin",
                        ],
                        args.dry_run,
                    )
                except subprocess.CalledProcessError as error:
                    print(
                        f"keep repository: {repo}: fetch failed: {error}",
                        file=sys.stderr,
                    )
                    failures = True
                    continue
            for entry in entries[1:]:
                wt = entry["worktree"]
                try:
                    print(f"inspect: {wt}", flush=True)
                    retire(repo, entry, args.dry_run)
                except Preserve as error:
                    print(f"keep: {wt}: {error}", flush=True)
                except (
                    OSError,
                    ValueError,
                    subprocess.CalledProcessError,
                    StopIteration,
                ) as error:
                    print(f"failed: {wt}: {error}", file=sys.stderr, flush=True)
                    failures = True
        if args.gc:
            try:
                builders_idle()
                execute(
                    [
                        "mbx",
                        "gc",
                        "--max-size",
                        "25GiB",
                        *(["--dry-run"] if args.dry_run else []),
                    ],
                    False,
                )
            except Preserve as error:
                print(f"skip MBX GC: {error}")
        if failures:
            raise Preserve("some cleanup operations failed; see the report above")


if __name__ == "__main__":
    try:
        main()
    except (OSError, Preserve, subprocess.CalledProcessError) as error:
        sys.exit(f"clean: {error}")
