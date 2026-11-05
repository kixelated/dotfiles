#!/usr/bin/env bash
# Install hourly cleanup from the same dotfiles checkout as this script.
set -euo pipefail
script_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$HOME/.local/bin" "$unit_dir"
for file in clean.sh clean-worktrees.py; do
	ln -sfn "$script_dir/$file" "$HOME/.local/bin/$file"
done
# Replace a previous timer, including a dangling link left when the 15-minute
# unit was removed. `disable` fails on that dangling link; stop and unlink it.
if [ -e "$unit_dir/worktree-clean.timer" ] || [ -L "$unit_dir/worktree-clean.timer" ]; then
	systemctl --user stop worktree-clean.timer || true
	rm -f "$unit_dir/worktree-clean.timer" "$unit_dir/timers.target.wants/worktree-clean.timer"
fi
ln -sfn "$script_dir/../systemd/worktree-clean.service" "$unit_dir/worktree-clean.service"
ln -sfn "$script_dir/../systemd/worktree-clean.timer" "$unit_dir/worktree-clean.timer"
systemctl --user daemon-reload
systemctl --user enable --now worktree-clean.timer
