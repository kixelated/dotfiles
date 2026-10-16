#!/usr/bin/env bash
# Install manual cleanup from the same dotfiles checkout as this script.
set -euo pipefail
script_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$HOME/.local/bin" "$unit_dir"
for file in clean.sh clean-worktrees.py; do
	ln -sfn "$script_dir/$file" "$HOME/.local/bin/$file"
done
if [ -e "$unit_dir/worktree-clean.timer" ] || [ -L "$unit_dir/worktree-clean.timer" ]; then
	systemctl --user disable --now worktree-clean.timer
fi
ln -sfn "$script_dir/../systemd/worktree-clean.service" "$unit_dir/worktree-clean.service"
systemctl --user daemon-reload
