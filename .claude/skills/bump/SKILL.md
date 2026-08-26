---
name: bump
description: Audit and apply semver version bumps for published packages with unreleased changes, skipping Rust crates when release-plz owns them. Use before a release or when asked whether package versions are stale. Convention here is patch for fixes and additive APIs, minor for breaking changes.
---

# Bump Packages

Audit package by package and bump only independently versioned release sources. First detect whether release-plz is configured (a tracked config file or release workflow, not a mere mention in docs or lockfiles); if so, Rust crate versions belong to it: leave them alone and say so in the report.

## Audit

1. Read the repo's `CLAUDE.md`/`AGENTS.md` and per-language guides; they own the versioning conventions.
2. Pick the comparison: on a feature branch, the merge-base diff against the target branch. On the target branch, changes since each package's last version-bump commit: `git log -- <version-file>` to find the bump, then `git log`/`git diff <bump>..HEAD -- <package-path>` for the unreleased work. Changes before that bump commit are already released.
3. Classify each changed package from actual exports, signatures, and behavior, never from commit prefixes alone:
   - **none**: docs, tests, internal refactors, private packages, generated bindings versioned elsewhere, dependency-only changes with no shipped effect.
   - **patch**: bug fixes, behavioral improvements, additive public APIs (the pre-1.0 convention here; don't escalate additive to minor just because semver would allow it).
   - **minor**: removed/renamed APIs, changed signatures or semantics, anything that breaks a consumer.
4. Dependents need a release only when their shipped contents or public contract changed; a version range that already accepts the new version does not by itself.

## Version sources (moq repo)

- Rust: release-plz owns crate versions and Rust dependency requirements; don't edit them.
- JavaScript: `js/*/package.json` packages with a `scripts.release` entry (skip private ones like `@moq/clock`, `@moq/wasm`), plus the matching workspace version in `bun.lock`.
- Python: `py/moq-rs/pyproject.toml` only; `py/moq-ffi` follows the `moq-ffi-v*` tag and Rust crate.
- Swift: `swift/VERSION`. Kotlin: `moq.version` in `kt/gradle.properties`. Their FFI counterparts track the Rust crate; don't bump them independently.
- Go: `go/wrapper/VERSION` holds a human-owned `MAJOR.MINOR` line; CI derives the patch, so only edit it for a breaking API. Leave the placeholder FFI version in `go.mod` alone.
- When a documented install version changes, grep the repo for the old coordinate/version and update every install example for that package.

## Apply and verify

Make the smallest exact manifest and lockfile edits (or run the repo's lockfile command when it changes only intended files). Then review `git diff --check` and the full diff, and run the affected packages' checks. Report each bump (old to new, and the change that requires it), packages examined but left unchanged and why (including release-plz skips), and the checks run. Never publish, tag, commit, or push unless the user asks.
