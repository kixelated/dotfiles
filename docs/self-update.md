# Self-update

`./install` schedules `bin/dotfiles-update` hourly: a systemd user timer on
Linux (`systemd/dotfiles-update.timer`) and a LaunchAgent on macOS
(`launchd/dotfiles-update.plist`, logging to `~/Library/Logs/dotfiles-update.log`).
It fast-forwards the checkout and reruns `./install` only when that moved it,
so a merged change reaches every machine within the hour.

A pull that cannot fast-forward, such as a checkout on another branch or with
conflicting local edits, fails the run instead of merging; check
`systemctl --user status dotfiles-update` or the log, and fix the checkout by
hand. Run `dotfiles-update` directly to update now.
