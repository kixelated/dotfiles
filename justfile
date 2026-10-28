# Verify the host cleanup policy using disposable Git repositories.
check:
    python3 -B -m unittest discover -s tests -v
    bash -n install bin/clean.sh bin/install-worktree-clean.sh
    systemd-analyze --user verify systemd/worktree-clean.service systemd/nix-gc.service systemd/nix-gc.timer
