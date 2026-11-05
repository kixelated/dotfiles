# Verify the host cleanup policy using disposable Git repositories.
check:
    python3 -B -m unittest discover -s tests -v
    bash -n install bin/clean.sh bin/install-worktree-clean.sh bin/dotfiles-update codex/bash-env.sh
    systemd-analyze --user verify systemd/worktree-clean.service systemd/worktree-clean.timer systemd/nix-gc.service systemd/nix-gc.timer systemd/dotfiles-update.service systemd/dotfiles-update.timer
    python3 -I -c 'import plistlib, sys; plistlib.load(open(sys.argv[1], "rb"))' launchd/dotfiles-update.plist
