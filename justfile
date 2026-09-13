# Verify the host cleanup policy using disposable Git repositories.
check:
    python3 -B -m unittest discover -s tests -v
    bash -n bin/clean.sh bin/install-worktree-clean.sh
    systemd-analyze --user verify systemd/worktree-clean.service systemd/worktree-clean.timer
