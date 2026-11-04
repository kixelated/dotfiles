# Build storage

`mbx/config.toml` keeps managed targets for every existing checkout. Binaries
started directly from `target/` hold no mbx lease, including the gaps between
benchmark runs. `target.keep = ["/"]` protects those outputs from both normal
collection and low-space collection on our Linux and macOS hosts. A target is
still collectible after its checkout disappears.

Pressure-driven collection is disabled with `gc.min_free_size = "none"`.
Normal action-store and incremental-state budgets remain enabled. Filling the
disk can therefore fail a build with `No space left on device` rather than
evicting other checkouts' targets or draining the shared cache below its budget.
This is an I/O failure policy, not a reservation or an early free-space check.

Inspect usage before choosing what to remove:

```sh
df -h .
du -xsh ~/worktrees ~/.cache/mbx /nix/store
mbx cache stats
mbx gc --dry-run
```

Use `quest worktree` in a quest repository to reclaim finished checkouts.
Explicit `mbx clean` and `mbx cache remove` can still remove a kept target;
run them only after confirming that its owner has finished using its outputs.
The manual worktree cleanup is described in [worktree-cleanup.md](worktree-cleanup.md).

Upstream's [managed-target documentation](https://mr-boxington.jdx.dev/managed-targets)
distinguishes a live checkout from a running command. Its process scan does
not protect directly launched programs when the disk is below
`gc.min_free_size`, even in mbx 1.29.2. Explicit retention avoids depending on
that scan, a recent-build grace period, or keeping a Cargo process alive.
