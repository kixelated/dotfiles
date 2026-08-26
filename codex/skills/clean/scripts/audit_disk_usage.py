#!/usr/bin/env python3
"""Read-only audit of common development disk consumers."""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable


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


def existing(paths: Iterable[Path]) -> list[Path]:
    return sorted({path.expanduser().resolve() for path in paths if path.exists()})


def expand(pattern: Path) -> list[Path]:
    return [Path(value) for value in glob.glob(str(pattern), recursive=True)]


def measured(path: Path, label: str) -> dict[str, Any]:
    amount, error = size_kib(path)
    return {"label": label, "path": str(path), "size_kib": amount, "error": error}


def sparse_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "logical_size_kib": stat.st_size // 1024,
        "allocated_size_kib": stat.st_blocks * 512 // 1024,
    }


def audit(home: Path, top: int) -> dict[str, Any]:
    usage = shutil.disk_usage(home)
    categories = [
        ("codex worktrees", home / ".codex" / "worktrees"),
        ("work repositories", home / "work"),
        ("kache compiler cache", home / "Library" / "Caches" / "kache"),
        ("general user cache", home / ".cache"),
        ("Podman storage", home / ".local" / "share" / "containers"),
        ("Docker Desktop storage", home / "Library" / "Containers" / "com.docker.docker"),
        ("Claude application data", home / "Library" / "Application Support" / "Claude"),
        ("Rust toolchains", home / ".rustup"),
        ("Android user data", home / ".android"),
        ("Android SDK data", home / "Library" / "Android"),
    ]

    target_patterns = [
        home / ".codex" / "worktrees" / "*" / "*" / "target",
        home / "work" / "*" / ".claude" / "worktrees" / "*" / "target",
        home / "work" / "*" / "target",
    ]
    targets = existing(path for pattern in target_patterns for path in expand(pattern))
    target_rows = [measured(path, "Cargo target") for path in targets]
    target_rows.sort(key=lambda row: row["size_kib"] or -1, reverse=True)

    sparse_patterns = [
        home / ".local" / "share" / "containers" / "podman" / "machine" / "**" / "*.raw",
        home / "Library" / "Containers" / "com.docker.docker" / "Data" / "vms" / "**" / "Docker.raw",
    ]
    sparse_paths = existing(path for pattern in sparse_patterns for path in expand(pattern))

    return {
        "home": str(home),
        "filesystem": {
            "total_kib": usage.total // 1024,
            "used_kib": usage.used // 1024,
            "free_kib": usage.free // 1024,
        },
        "categories": [measured(path, label) for label, path in categories if path.exists()],
        "cargo_targets": {
            "count": len(target_rows),
            "total_size_kib": sum(row["size_kib"] or 0 for row in target_rows),
            "largest": target_rows[:top],
        },
        "sparse_vm_disks": [sparse_file(path) for path in sparse_paths],
        "note": "Audit only. Size does not imply cleanup safety.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="Home directory to audit")
    parser.add_argument("--top", type=int, default=20, help="Number of Cargo targets to report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.top < 1:
        raise SystemExit("--top must be positive")
    home = args.home.expanduser().resolve()
    if not home.is_dir():
        raise SystemExit(f"not a directory: {home}")
    print(json.dumps(audit(home, args.top), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
