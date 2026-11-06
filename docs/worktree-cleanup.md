# Worktree cleanup

On Linux with systemd, `./install` installs the user `worktree-clean.service`
and an hourly `worktree-clean.timer`. The same step can be run separately with
`bin/install-worktree-clean.sh`. The timer is persistent, with a ten-minute
randomized delay, so a missed hour runs after the next boot. Overlapping runs
are prevented with a lock. The oneshot service allows up to two hours and scans
`~/work`, `~/worktrees`, `~/.codex/worktrees`, `~/.worktrees`, and `/tmp`.

A 15-minute timer was removed because each pass spent more time fetching and
asking GitHub than the disk needed. Cleanup then ran only by hand. On
2026-11-04 the root disk filled the same day while parallel agent builds held
managed targets, and nobody started the service. An hourly pass reclaims a
finished checkout without polling every few minutes. Start the service by hand
for an immediate pass:

```sh
systemctl --user start worktree-clean.service
systemctl --user status worktree-clean.service
journalctl --user -u worktree-clean.service
```

On hosts without a reachable systemd user manager (for example, containers),
dotfiles installation skips the service and continues configuring the other files.

The cleaner keeps main checkouts, locks, hidden index changes, active processes
and targets, submodule stashes, and local-only submodule commits. A dirty or
untracked checkout stays on disk. Missing or failed inspection preserves the
checkout. Preliminary inspections share an activity snapshot; every removal
checks fresh host activity. Branches are never deleted.

A checkout is reclaimed when its branch is an ancestor of the base, its HEAD is
in the commit history of a merged GitHub PR whose merge commit survives on that
PR's actual base, its HEAD is in the history of a closed PR, or it tracks its
own deleted origin branch. A finished T3 thread, or a released quest checkout
with no supervised runs, is complete even when its branch is still open. Claude
Code checkouts under `.claude/worktrees` are finished once a project transcript
exists. A missing transcript uses the git rules above. Idle time is not a
signal. An unknown `t3-*` checkout, a database or registry error, a live
session, or a non-terminal run keeps the checkout and its managed target.

When the owner is finished but the checkout is still dirty, the checkout stays
and `mbx cache remove` runs for its managed workspace targets after a fresh
process check. A process in the checkout or the target keeps both.

Other remotes are not refreshed and cannot prove deletion. An inherited
upstream of `origin/main` is not the feature's upstream. GitHub proofs cover
squash merges, local branch aliases, earlier PR iterations, and release
branches. Commits added after the merged or closed PR head do not qualify.
Proof is refreshed when the actual base branch tip changes. Detached HEADs need
a surviving local branch or tag, including when an agent signal says the
checkout is finished. A live run fetches/prunes origin first; a dry run leaves
refs unchanged. `/tmp` is scanned for registered worktrees only. Age does not
delete test scratch such as `/tmp/moq-test-*`.

```sh
clean.sh --dry-run
```

Ignored files (drafts, logs, build output) go with the checkout: once its work
is proven merged, Git removes them with the worktree. Nothing is backed up, so
keep anything worth saving in a commit or outside the checkout.

Initialized submodules can be retired only after the above checks, using Git's
single-force worktree removal. Independent nested Git repositories, including
ones hidden inside artifact directories, remain protected: their links and
local history need separate handling. This does not change Codex's own archive
restriction on nested repositories.

The service also releases idle MBX workspace claims and runs MBX GC with a
25 GiB object-cache budget when no builders or managed targets are active.

## Keep new worktrees clean

Keep PR text, review drafts, logs, inspection patches, helper scripts, and
temporary clones in the checkout's ignored `.tmp/`, which retirement removes
with the worktree (the `quest guide` Workspace rule).
Commit intended source changes before ending a task and restore only generated
changes from that task's own checks.
Track the actual PR branch when pushing so completion remains discoverable.
The shared Claude/Codex instructions enforce this workflow for new tasks.
