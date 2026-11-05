# Self-update

`./install` schedules `bin/dotfiles-update` hourly: a systemd user timer on
Linux (`systemd/dotfiles-update.timer`) and a LaunchAgent on macOS
(`launchd/dotfiles-update.plist`, logging to `~/Library/Logs/dotfiles-update.log`).
It fast-forwards the checkout and reruns `./install` until the checked-out
commit has installed successfully (recorded in `.git/dotfiles-installed`), so a
merged change reaches every machine within the hour and a failed install is
retried the next hour. A changed LaunchAgent definition is reloaded only by a
manual `./install`, since unloading the agent from its own run would kill it.

A pull that cannot fast-forward, such as a checkout on another branch or with
conflicting local edits, fails the run instead of merging; check
`systemctl --user status dotfiles-update` or the log, and fix the checkout by
hand. Run `dotfiles-update` directly to update now.
