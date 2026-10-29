---
name: bump
description: Audit and apply semver version bumps for published packages with unreleased changes, skipping Rust crates when release-plz owns them. Use before a release or when asked whether package versions are stale.
---

Bump the versions of packages with unreleased changes, one package at a time.
If unsure about any course of action, pause and prompt the user for guidance.

- Read the repo's `AGENTS.md`, `CONTRIBUTING.md`, and per-language guides; they own the versioning conventions and say where each package's version lives.
- Check for release-plz (a tracked config or release workflow, not a mention in docs or lockfiles). If present, it owns Rust crate versions: leave them alone and say so.
- Pick the comparison. On a feature branch, diff against the merge-base with the target branch. On the target branch, find each package's last version-bump commit (`git log -- <version-file>`) and diff from there; anything older is already released.
- Classify each changed package from its actual exports, signatures, and behavior, never from commit prefixes:
  - **none** for docs, tests, internal refactors, private packages, and dependency-only changes with no shipped effect.
  - **patch** for bug fixes and behavioral improvements, plus additive public APIs on a pre-1.0 package.
  - **minor** for additive public APIs at 1.0 or later, and for breaking changes before 1.0.
  - **major** for breaking changes at 1.0 or later: removed/renamed APIs, changed signatures or semantics, anything that breaks a consumer.
- Bump a dependent only when its own shipped contents or public contract changed. A version range that already accepts the new version is not a reason.
- Make the smallest exact manifest and lockfile edits, or run the repo's lockfile command when it only touches intended files.
- Grep for the old coordinate and update every install example when a documented version changes.
- Review the full diff, run the affected packages' checks, and report each bump with the change that requires it, plus what you examined and left alone and why.
- Never publish, tag, commit, or push unless the user asks.
