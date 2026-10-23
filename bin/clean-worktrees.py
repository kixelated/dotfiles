#!/usr/bin/env python3
"""Retire inactive Git worktrees through Git and MBX, never by raw deletion."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from functools import cache
from pathlib import Path


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
        check=False,
    )
    if result.returncode or not result.stdout:
        raise Preserve(f"cannot inspect activity: {result.stderr.strip()}")
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("n/"):
            paths.append(Path(line[1:].removesuffix(" (deleted)")))
    return paths


def idle(paths, activity=None):
    roots = {str(path) for path in paths}
    prefixes = tuple(path.rstrip("/") + "/" for path in roots)
    for active in processes() if activity is None else activity:
        name = str(active)
        if name in roots or name.startswith(prefixes):
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


def local_data(repo):
    """Inspect ignored roots once, including nested repos inside build output."""
    found = []

    @cache
    def cargo_cache(parts):
        marker = repo.joinpath(*parts, "CACHEDIR.TAG")
        try:
            return marker.read_bytes().startswith(
                b"Signature: 8a477f597d28d172789f06886806bc55"
            )
        except (FileNotFoundError, NotADirectoryError):
            return False

    def artifact(path):
        for index, part in enumerate(path.parts):
            if part in ARTIFACTS:
                # Match Cargo's refusal to delete an unmarked target. Older
                # agent checkouts contain drafts and helper scripts there.
                return part != "target" or cargo_cache(path.parts[:index + 1])
        return path.suffix == ".tsbuildinfo"

    def record(path):
        if not artifact(path.relative_to(repo)):
            found.append(path)

    for raw in git(
        repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"
    ).split(b"\0"):
        if not raw:
            continue
        path = Path(os.fsdecode(raw))
        full = repo / path
        if path.is_absolute() or ".." in path.parts:
            raise Preserve(f"ignored path escapes checkout: {path}")
        for parent in (full, *full.parents):
            if parent == repo:
                break
            if (
                parent.name == ".git"
                or (parent / ".git").exists()
                or (parent / ".git").is_symlink()
                or ((parent / "HEAD").is_file() and (parent / "objects").is_dir())
            ):
                raise Preserve(f"independent nested Git repository: {parent}")
            if parent != full and parent.is_symlink():
                raise Preserve(f"ignored path traverses a symlink: {full}")
        if not full.is_dir() or full.is_symlink():
            record(full)
            continue

        def failed(error):
            raise error

        # Git collapses ignored directories; walk them once without following
        # links. Inspect directory entries for Git repositories, not every
        # artifact file's ancestors (which made dependency trees very costly).
        for directory, dirs, files in os.walk(full, followlinks=False, onerror=failed):
            root = Path(directory)
            if ".git" in dirs or ".git" in files or ("HEAD" in files and "objects" in dirs):
                raise Preserve(f"independent nested Git repository: {root}")
            if artifact(root.relative_to(repo)):
                continue
            for name in list(dirs):
                child = root / name
                if child.is_symlink():
                    dirs.remove(name)
                    record(child)
            for name in files:
                record(root / name)
    return sorted(found)


def fingerprint(path):
    info = path.lstat()
    if path.is_symlink():
        content = {"symlink": os.readlink(path)}
    elif path.is_file():
        with path.open("rb") as stream:
            content = {"sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    else:
        raise Preserve(f"unsupported local data: {path}")
    return {
        **content,
        "mode": info.st_mode,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }


def archive_local_data(wt, paths, dry):
    """Copy and verify data before Git removes its original checkout."""
    state = Path(
        os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
    ).resolve()
    destination = state / "worktree-clean/archives" / uuid.uuid4().hex
    print(f"  archive {len(paths)} local files: {destination}", flush=True)
    if dry:
        return {}
    destination.mkdir(parents=True, mode=0o700)
    manifest = {"worktree": str(wt), "head": text(wt, "rev-parse", "HEAD"), "files": {}}
    for source in paths:
        relative = source.relative_to(wt)
        before = fingerprint(source)
        target = destination / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(source, target, follow_symlinks=False)
        if not target.is_symlink():
            with target.open("rb") as stream:
                os.fsync(stream.fileno())
        if fingerprint(source) != before or fingerprint(target) != before:
            raise Preserve(f"archive verification failed: {source}; kept {destination}")
        manifest["files"][str(relative)] = before
    with (destination / "manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    # Persist directory entries too; source deletion must not outrun the backup.
    directories = {destination}
    parent = destination.parent
    while parent != state.parent:
        directories.add(parent)
        parent = parent.parent
    for source in paths:
        parent = (destination / "files" / source.relative_to(wt)).parent
        while parent != destination:
            directories.add(parent)
            parent = parent.parent
    for directory in sorted(
        directories, key=lambda path: len(path.parts), reverse=True
    ):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return {wt / path: value for path, value in manifest["files"].items()}


def ancestor(repo, head, ref):
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", head, ref],
        capture_output=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise Preserve(f"cannot inspect merge ancestry: {ref}")
    return result.returncode == 0


@cache
def pull_request_evidence(repo):
    """Cache both successes and failures, avoiding an API retry per worktree."""
    url = text(repo, "remote", "get-url", "origin")
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?/?", url
    )
    if not match:
        return []
    query = """query($owner:String!,$name:String!,$endCursor:String){
      repository(owner:$owner,name:$name){
        pullRequests(first:100,states:MERGED,after:$endCursor){
          nodes{headRefName headRefOid baseRefName mergeCommit{oid}}
          pageInfo{hasNextPage endCursor}
        }
      }
    }"""
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                f"query={query}",
                "-F",
                f"owner={match[1]}",
                "-F",
                f"name={match[2]}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Preserve(f"cannot verify merged pull requests: {error}")
    if result.returncode:
        return Preserve(f"cannot verify merged pull requests: {result.stderr.strip()}")
    try:
        pages = json.loads(result.stdout)
        prs = [
            pr
            for page in pages
            for pr in page["data"]["repository"]["pullRequests"]["nodes"]
        ]
        if not isinstance(pages, list) or not all(isinstance(pr, dict) for pr in prs):
            raise ValueError("expected paginated PR objects")
        return prs
    except (ValueError, KeyError, TypeError):
        return Preserve("invalid merged pull request response")


def merged_pull_requests(repo):
    evidence = pull_request_evidence(repo)
    if isinstance(evidence, Preserve):
        raise evidence
    return evidence


def completed_pr_commits(repo):
    """Use commit identity, including earlier iterations, rather than branch names."""
    prs = merged_pull_requests(repo)
    refs = sorted(
        {
            f"refs/remotes/origin/{pr['baseRefName']}"
            for pr in prs
            if isinstance(pr.get("baseRefName"), str) and pr["baseRefName"]
        }
    )
    if not refs:
        return frozenset()
    # Key the cache by current base tips: a force-push must invalidate old proof.
    bases = tuple(
        text(repo, "for-each-ref", "--format=%(refname) %(objectname)", *refs).splitlines()
    )
    return completed_pr_commits_at_bases(repo, bases)


@cache
def completed_pr_commits_at_bases(repo, bases):
    reachable = {
        ref: set(text(repo, "rev-list", tip).splitlines())
        for ref, tip in (line.split() for line in bases)
    }
    heads = set()
    for pr in merged_pull_requests(repo):
        head = pr.get("headRefOid")
        merge = pr.get("mergeCommit") or {}
        base = f"refs/remotes/origin/{pr.get('baseRefName', '')}"
        if (
            isinstance(head, str)
            and re.fullmatch(r"[0-9a-f]{40,64}", head)
            and isinstance(merge, dict)
            and isinstance(merge.get("oid"), str)
            and merge["oid"] in reachable.get(base, set())
        ):
            heads.add(head)
    if not heads:
        return frozenset()
    # Deleted PR branches need not exist locally. Only walk available commits;
    # missing objects provide no proof and never trigger one fetch per PR.
    objects = subprocess.check_output(
        [
            "git", "-C", str(repo), "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
        ],
        input="".join(head + "\n" for head in sorted(heads)).encode(),
        stderr=subprocess.PIPE,
    )
    available = [
        line.split()[0] for line in objects.splitlines() if line.endswith(b" commit")
    ]
    if not available:
        return frozenset()
    commits = subprocess.check_output(
        ["git", "-C", str(repo), "rev-list", "--stdin"],
        input=b"\n".join(available) + b"\n",
        stderr=subprocess.PIPE,
    )
    return frozenset(os.fsdecode(commits).splitlines())


def completed_branch(repo, entry, head):
    for ref in (
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/main",
        "refs/remotes/origin/master",
    ):
        if text(repo, "for-each-ref", "--format=%(refname)", ref) and ancestor(
            repo, head, ref
        ):
            return
    branch = entry["branch"].removeprefix("refs/heads/")
    # An inherited upstream of origin/main is not this feature's PR branch.
    # Only use "gone upstream" when it actually tracked this branch's name.
    upstream = text(repo, "for-each-ref", "--format=%(upstream)", entry["branch"])
    remote = (
        text(repo, "config", "--get", f"branch.{branch}.remote") if upstream else ""
    )
    if (
        remote == "origin"  # This is the remote main() refreshes before removal.
        and upstream == f"refs/remotes/{remote}/{branch}"
        and not text(repo, "for-each-ref", "--format=%(refname)", upstream)
    ):
        return
    # Local branch aliases and commits from earlier PR iterations are complete
    # too. Descendants added after the merged PR head still block retirement.
    if (
        "origin" in text(repo, "remote").splitlines()
        and head in completed_pr_commits(repo)
    ):
        return
    raise Preserve(
        "branch has no verified completion (base ancestry, matching merged PR, or gone branch upstream)"
    )


def eligible(repo, entry, activity=None):
    wt = Path(entry["worktree"])
    if "locked" in entry or "prunable" in entry or not wt.is_dir():
        raise Preserve("locked, missing or prunable")
    if wt.is_symlink() or wt.resolve() != wt:
        raise Preserve("noncanonical worktree path")
    head = text(wt, "rev-parse", "HEAD")
    if "branch" not in entry:
        if not text(
            repo, "for-each-ref", f"--contains={head}", "refs/heads", "refs/tags"
        ):
            raise Preserve("detached commit has no surviving local branch or tag")
    else:
        completed_branch(repo, entry, head)
    clean(wt)
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
    idle(protected, activity)
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


def retire(repo, entry, dry, archive=False, activity=None):
    wt = Path(entry["worktree"])
    repos = eligible(repo, entry, activity)
    # Refresh the lock and status after the audit, before releasing cache claims.
    fresh = next(item for item in worktrees(repo) if item["worktree"] == str(wt))
    if fresh != entry:
        raise Preserve("worktree registration changed during audit")
    eligible(repo, fresh, activity)
    # Inspect before MBX can remove an artifact directory containing user data.
    for root in repos:
        local_data(root)
    targets = workspace_targets(wt)
    protected = [wt, *(target for paths in targets.values() for target in paths)]
    idle(protected, activity)
    # MBX accepts a workspace path, including one with no recorded claim.
    for root in sorted(
        set(repos) | set(targets), key=lambda path: len(path.parts), reverse=True
    ):
        idle(
            [wt, *targets.get(root, []), (root / "target").resolve()],
            activity if dry else None,
        )
        execute(["mbx", "cache", "remove", root], dry)
    eligible(repo, fresh, activity)
    # Ignored drafts and old package configs are data, not disposable artifacts.
    paths = sorted(path for root in repos for path in local_data(root))
    if paths and not archive:
        raise Preserve(
            f"ignored local data: {paths[0]} (use --archive-local-data to back up)"
        )
    saved = archive_local_data(wt, paths, dry) if paths else {}
    if saved:
        eligible(repo, fresh, activity)
        current = sorted(path for root in repos for path in local_data(root))
        if current != paths or any(fingerprint(path) != saved[path] for path in paths):
            raise Preserve("local data changed during archive; backup retained")
    # Do not deinit: it mutates shared submodule configuration. Git owns removal
    # of the worktree and its per-worktree module metadata. One force only.
    has_modules = any(
        line.startswith(b"160000 ")
        for line in git(wt, "ls-files", "--stage").splitlines()
    )
    command = ["git", "-C", repo, "worktree", "remove"]
    if has_modules:
        command.append("--force")
    # Preliminary scans can share a snapshot, but every mutation needs a fresh
    # host inspection, including newly started processes and external targets.
    idle(
        [*protected, *((root / "target").resolve() for root in repos)],
        activity if dry else None,
    )
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
                    # Discovery may start inside a removable linked checkout.
                    # Its shared gitdir survives every linked-tree retirement.
                    yield Path(common)
                dirs.clear()
            elif len(path.relative_to(root).parts) >= 4:
                dirs.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("--root", action="append", type=Path)
    parser.add_argument(
        "--archive-local-data",
        action="store_true",
        help="back up and verify ignored local files before retirement; keep nested repositories",
    )
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
        activity = (
            processes()
        )  # Never interpret a sandbox's partial view as inactivity.
        failures = False
        roots = args.root or [
            Path.home() / "work",
            Path.home() / ".codex/worktrees",
            Path.home() / ".worktrees",
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
                    retire(repo, entry, args.dry_run, args.archive_local_data, activity)
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
