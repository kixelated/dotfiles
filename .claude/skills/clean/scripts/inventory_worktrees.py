#!/usr/bin/env python3
"""Read-only inventory of registered Git worktrees and their cleanup signals."""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}


def run_git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def output(path: Path, *args: str) -> str | None:
    result = run_git(path, *args)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def default_roots() -> list[Path]:
    home = Path.home()
    roots = [Path.cwd(), home / ".codex" / "worktrees"]
    roots.extend(Path(path) for path in glob.glob(str(home / "work" / "*" / ".claude" / "worktrees")))
    return roots


def discover_seed_repositories(roots: Iterable[Path], max_depth: int) -> tuple[set[Path], list[str]]:
    seeds: set[Path] = set()
    warnings: list[str] = []

    for original_root in roots:
        root = original_root.expanduser().resolve()
        if not root.exists():
            continue
        if not root.is_dir():
            warnings.append(f"not a directory: {root}")
            continue

        direct_top = output(root, "rev-parse", "--show-toplevel")
        if direct_top:
            seeds.add(Path(direct_top).resolve())

        root_depth = len(root.parts)
        try:
            for current, directories, files in os.walk(root):
                current_path = Path(current)
                depth = len(current_path.parts) - root_depth
                directories[:] = [
                    name
                    for name in directories
                    if name not in SKIP_DIRS and depth < max_depth
                ]
                if ".git" not in files and ".git" not in os.listdir(current_path):
                    continue
                top = output(current_path, "rev-parse", "--show-toplevel")
                if top:
                    seeds.add(Path(top).resolve())
                directories[:] = []
        except OSError as error:
            warnings.append(f"could not scan {root}: {error}")

    return seeds, warnings


def parse_porcelain(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in [*text.splitlines(), ""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"bare", "detached"}:
            current[key] = True
        elif key in {"locked", "prunable"}:
            current[key] = value or True
        else:
            current[key] = value
    return records


def detect_base_ref(seed: Path) -> str | None:
    remote_head = output(seed, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if remote_head and output(seed, "rev-parse", "--verify", "--quiet", remote_head):
        return remote_head
    for candidate in ("refs/heads/main", "refs/heads/master", "refs/heads/trunk"):
        if output(seed, "rev-parse", "--verify", "--quiet", candidate):
            return candidate
    return None


def branch_details(seed: Path, branch_ref: str | None) -> dict[str, Any]:
    if not branch_ref:
        return {"name": None, "upstream": None, "upstream_track": None}
    formatted = output(
        seed,
        "for-each-ref",
        "--format=%(refname:short)%00%(upstream:short)%00%(upstream:track)",
        branch_ref,
    )
    if not formatted:
        return {"name": branch_ref.removeprefix("refs/heads/"), "upstream": None, "upstream_track": None}
    name, upstream, track = (formatted.split("\0") + ["", ""])[:3]
    return {
        "name": name or branch_ref.removeprefix("refs/heads/"),
        "upstream": upstream or None,
        "upstream_track": track or None,
    }


def ecosystem_markers(path: Path) -> list[str]:
    markers = {
        "rust": ["Cargo.toml"],
        "javascript": ["package.json"],
        "swift": ["Package.swift"],
        "gradle": ["gradlew", "build.gradle", "build.gradle.kts"],
        "maven": ["mvnw", "pom.xml"],
        "dotnet": ["*.sln", "*.csproj", "*.fsproj"],
        "go": ["go.mod"],
        "cmake": ["CMakeLists.txt"],
        "bazel": ["WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel"],
        "python": ["pyproject.toml", "setup.py"],
        "make": ["Makefile", "makefile"],
        "just": ["justfile", "Justfile"],
    }
    found: list[str] = []
    for ecosystem, patterns in markers.items():
        if any(any(path.glob(pattern)) for pattern in patterns):
            found.append(ecosystem)
    return found


def size_kib(path: Path) -> tuple[int | None, str | None]:
    result = subprocess.run(
        ["du", "-sk", str(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "du failed"
    try:
        return int(result.stdout.split()[0]), None
    except (IndexError, ValueError):
        return None, "unexpected du output"


def contains_refs(seed: Path, head: str) -> list[str]:
    refs = output(
        seed,
        "for-each-ref",
        "--format=%(refname)",
        "--contains",
        head,
        "refs/heads",
        "refs/remotes",
        "refs/tags",
    )
    return refs.splitlines() if refs else []


def inspect_worktree(
    seed: Path,
    record: dict[str, Any],
    base_ref: str | None,
    sizes: bool,
    is_main_worktree: bool,
) -> dict[str, Any]:
    path = Path(record.get("worktree", "")).expanduser()
    exists = path.is_dir()
    head = record.get("HEAD")
    branch_ref = record.get("branch")
    item: dict[str, Any] = {
        "path": str(path),
        "is_main_worktree": is_main_worktree,
        "exists": exists,
        "bare": bool(record.get("bare")),
        "detached": bool(record.get("detached")),
        "locked": record.get("locked", False),
        "prunable": record.get("prunable", False),
        "head": head,
        "branch": branch_details(seed, branch_ref),
        "base_ref": base_ref,
        "head_merged_into_base": None,
        "containing_refs": [],
        "clean": None,
        "status_entries": None,
        "ecosystems": [],
        "size_kib": None,
        "cargo_target_size_kib": None,
        "errors": [],
    }

    if head and base_ref:
        merged = run_git(seed, "merge-base", "--is-ancestor", head, base_ref)
        if merged.returncode in (0, 1):
            item["head_merged_into_base"] = merged.returncode == 0
    if head:
        item["containing_refs"] = contains_refs(seed, head)

    if not exists or item["bare"]:
        return item

    status = run_git(path, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode == 0:
        entries = [line for line in status.stdout.splitlines() if line]
        item["clean"] = not entries
        item["status_entries"] = len(entries)
    else:
        item["errors"].append(status.stderr.strip() or "git status failed")

    item["ecosystems"] = ecosystem_markers(path)
    if sizes:
        measured, error = size_kib(path)
        item["size_kib"] = measured
        if error:
            item["errors"].append(error)
        cargo_target = path / "target"
        if cargo_target.is_dir():
            measured, error = size_kib(cargo_target)
            item["cargo_target_size_kib"] = measured
            if error:
                item["errors"].append(f"cargo target: {error}")
    return item


def inventory(roots: list[Path], max_depth: int, sizes: bool) -> dict[str, Any]:
    seeds, warnings = discover_seed_repositories(roots, max_depth)
    repositories: list[dict[str, Any]] = []
    seen_common_dirs: set[str] = set()

    for seed in sorted(seeds):
        common_dir = output(seed, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if not common_dir:
            warnings.append(f"could not resolve Git common directory for {seed}")
            continue
        if common_dir in seen_common_dirs:
            continue
        seen_common_dirs.add(common_dir)

        listed = run_git(seed, "worktree", "list", "--porcelain")
        if listed.returncode != 0:
            warnings.append(listed.stderr.strip() or f"could not list worktrees for {seed}")
            continue
        records = parse_porcelain(listed.stdout)
        base_ref = detect_base_ref(seed)
        repositories.append(
            {
                "git_common_dir": common_dir,
                "seed": str(seed),
                "base_ref": base_ref,
                "worktrees": [
                    inspect_worktree(seed, record, base_ref, sizes, index == 0)
                    for index, record in enumerate(records)
                ],
            }
        )

    return {
        "roots": [str(path.expanduser().resolve()) for path in roots],
        "repositories": repositories,
        "warnings": warnings,
        "note": "Inventory only. Activity checks and conservative classification are still required.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path, help="Roots containing Git worktrees")
    parser.add_argument("--max-depth", type=int, default=4, help="Maximum discovery depth per root (default: 4)")
    parser.add_argument("--sizes", action="store_true", help="Measure approximate worktree sizes with du -sk")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_depth < 0:
        print("--max-depth must be non-negative", file=sys.stderr)
        return 2
    roots = args.roots or default_roots()
    print(json.dumps(inventory(roots, args.max_depth, args.sizes), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
