# Worktree cleanup

On Linux with systemd, `./install` installs the manual **user**
`worktree-clean.service` and disables any old automatic cleanup timer. The same
step can be run separately with `bin/install-worktree-clean.sh`. Start cleanup
when needed; the oneshot service scans `~/work`, `~/.codex/worktrees`,
`~/.worktrees`, and `/tmp`. Overlapping runs are prevented with a lock. The
service allows up to two hours for large inventories:

```sh
systemctl --user start worktree-clean.service
systemctl --user status worktree-clean.service
journalctl --user -u worktree-clean.service
```

On hosts without a reachable systemd user manager (for example, containers),
dotfiles installation skips the service and continues configuring the other files.

The cleaner keeps main checkouts, locks, dirty/untracked files, hidden index
changes, active processes and targets, submodule stashes, and local-only
submodule commits. Missing or failed inspection preserves the checkout.
Preliminary inspections share an activity snapshot; every removal checks fresh
host activity. Branches are never deleted.

A branch must be an ancestor of the base, have a HEAD included in the commit
history of a merged GitHub PR whose merge commit survives on that PR's actual
base, or track its own deleted
origin branch. Other remotes are not refreshed and cannot prove deletion.
An inherited upstream of `origin/main` is not the feature's
upstream. GitHub proofs cover squash merges, local branch aliases, earlier PR
iterations,
and release branches. Commits added after the merged PR head do not qualify.
Proof is refreshed when the actual base branch tip changes. Detached HEADs need
a surviving local branch or tag. A live run fetches/prunes origin first; a dry run leaves refs unchanged.

```sh
clean.sh --dry-run --archive-local-data
```

The public `clean.sh` command and service enable `--archive-local-data` by
default: ignored drafts, old package configs, and other local files are copied into
`${XDG_STATE_HOME:-$HOME/.local/state}/worktree-clean/archives/<id>/` before Git
removes the checkout. Copies preserve symlinks, permissions, and timestamps;
content hashes and metadata are verified, files/directories are synced, and
changes during backup preserve the original. Backups are never automatically
purged. A `target/` directory without a valid Cargo `CACHEDIR.TAG` is archived
as local data, since older checkouts can contain drafts and scripts there. A failed backup leaves the original intact (and may leave a partial
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

## Keep new worktrees clean

Keep PR text, review drafts, logs, inspection patches, helper scripts, and
temporary clones in a per-task directory outside the checkout (`mktemp -d`).
Commit intended source changes before ending a task and restore only generated
changes from that task's own checks. Do not hide scratch with new ignore rules.
Track the actual PR branch when pushing so completion remains discoverable.
The shared Claude/Codex instructions enforce this workflow for new tasks.
