# Worktree cleanup

On Linux with systemd, `./install` installs and enables the **user**
`worktree-clean.timer`. The same step can be run separately with
`bin/install-worktree-clean.sh`. Every 15 minutes the oneshot service scans
`~/work`, `~/.codex/worktrees`, `~/.worktrees`, and `/tmp`. Overlapping runs are
prevented with a lock. A full scan can exceed one timer interval; the service
allows up to two hours for large inventories. Inspect it with:

```sh
systemctl --user status worktree-clean.timer
journalctl --user -u worktree-clean.service
```

The cleaner keeps main checkouts, locks, dirty/untracked files, hidden index
changes, active processes and targets, submodule stashes, and local-only
submodule commits. Missing or failed inspection preserves the checkout.
Preliminary inspections share an activity snapshot; every removal checks fresh
host activity. Branches are never deleted.

A branch must be an ancestor of the base, have an exact-HEAD merged GitHub PR
whose merge commit survives on that PR's actual base, or track its own deleted
origin branch. Other remotes are not refreshed and cannot prove deletion.
An inherited upstream of `origin/main` is not the feature's
upstream. GitHub proofs cover squash merges and release branches; commits made
after a merge do not qualify. Detached HEADs need a surviving local branch or
tag. A live run fetches/prunes origin first; a dry run leaves refs unchanged.

```sh
clean.sh --dry-run --archive-local-data
```

The service enables `--archive-local-data`: ignored drafts, old package configs,
and other local files are copied into
`${XDG_STATE_HOME:-$HOME/.local/state}/worktree-clean/archives/<id>/` before Git
removes the checkout. Copies preserve symlinks, permissions, and timestamps;
content hashes and metadata are verified, files/directories are synced, and
changes during backup preserve the original. Backups are never automatically
purged. A failed backup leaves the original intact (and may leave a partial
backup).

Each completed backup has a `manifest.json` with the original checkout path,
HEAD, and file fingerprints. To restore, create a checkout at that HEAD,
initialize its submodules, then copy the contents of the backup's `files/` into
the checkout, preserving metadata and symlinks. The relative paths also cover
files inside submodules. Inspect a backup before restoring over existing work.

Initialized submodules can be retired only after the above checks, using Git's
single-force worktree removal. Independent nested Git repositories, including
ones hidden inside artifact directories, remain protected: their links and
local history need separate handling. This does not change Codex's own archive
restriction on nested repositories.

The service also releases idle MBX workspace claims and runs MBX GC with a
25 GiB object-cache budget when no builders or managed targets are active.
