---
name: bump-non-rust-packages
description: Audit and apply semver version bumps for MoQ packages outside the Rust workspace. Use when non-Rust APIs or behavior changed, before releasing JavaScript, Python, Swift, Kotlin, or Go packages, or when asked whether package versions are stale. Prefer patch bumps for fixes and additive APIs, and minor bumps for breaking APIs.
---

# Bump Non-Rust Packages

Audit changes package by package, update only independently versioned release sources, and keep generated or lockstep bindings aligned with their owning Rust crate.

## Audit

1. Read the repository `AGENTS.md` or `CLAUDE.md`, plus the guide for each affected language.
2. Identify the intended comparison:
   - On a feature branch, inspect the merge-base diff against the target branch.
   - On the target branch or a clean detached checkout, inspect changes since each package's latest version-bump commit.
3. Map changed public files to published packages. Do not infer a bump from commit prefixes alone. Inspect exports, signatures, types, documented behavior, wire behavior, and user-visible fixes.
4. Classify each changed package:
   - No bump: docs, tests, internal refactors, dependency-only changes with no shipped effect, private packages, or generated bindings whose version is owned elsewhere.
   - Patch: bug fixes, behavioral improvements, dependency fixes that affect consumers, and additive public APIs.
   - Minor: removed or renamed APIs, changed signatures or semantics, newly invalid call patterns, and other breaking consumer changes.
5. Treat pre-1.0 packages by the repository rule above. Do not turn an additive API into a minor bump merely because standard semver permits it.
6. Check dependents only when their shipped contents or public contract changed. A dependency range that already accepts the new version does not require a release by itself.

Use `git log -- <version-file>` to find the last bump, then `git log <bump-commit>..HEAD -- <package-path>` and `git diff <bump-commit>..HEAD -- <package-path>` to inspect unreleased work. Account for a bump commit that included other package changes: changes earlier than that commit are already released by that bump.

## Version Sources

- JavaScript: bump published `js/*/package.json` packages that have a `scripts.release` entry. Skip private packages such as `@moq/clock` and `@moq/wasm`. Update the matching workspace version in `bun.lock`.
- Python wrapper: bump `py/moq-rs/pyproject.toml`. Do not bump `py/moq-ffi`; its version comes from the `moq-ffi-v*` tag and Rust crate.
- Swift wrapper: bump `swift/VERSION`. Update committed install examples or generated-template expectations that contain the wrapper version. Do not independently bump `MoqFFI`.
- Kotlin wrapper: bump `moq.version` in `kt/gradle.properties`. Update committed install examples containing that version. Do not bump `moqffi.version`; CI supplies it from the Rust release.
- Go wrapper: `go/wrapper/VERSION` contains only the human-owned `MAJOR.MINOR` line. Keep it unchanged for fixes and additive APIs because CI derives the next patch. Bump the line for a breaking API. Do not edit the placeholder FFI version in `go.mod`.
- Raw FFI packages for Python, Swift, Kotlin, and Go track `rs/moq-ffi`; audit the Rust crate version rather than inventing independent non-Rust versions.

When changing a documented install version, search the repository for the old coordinate or version and update every canonical installation example for that same package.

## Apply and Verify

1. Use the repository's normal formatter or lockfile command when it changes only intended files. Otherwise make the smallest exact manifest and lockfile edits.
2. Review `git diff --check` and the full version diff.
3. Run focused checks for affected packages. For JavaScript manifest-only bumps, validate JSON and run the relevant package checks when practical.
4. Report:
   - each package and old to new version,
   - the change that requires the bump,
   - packages reviewed but intentionally unchanged and why,
   - checks run.

Do not publish, tag, commit, or push unless the user asks.
