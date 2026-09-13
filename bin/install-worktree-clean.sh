#!/usr/bin/env bash
# Install the user timer from the same dotfiles checkout as this script.
set -euo pipefail
script_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user"
for file in clean.sh clean-worktrees.py; do
	ln -sfn "$script_dir/$file" "$HOME/.local/bin/$file"
done
for unit in worktree-clean.service worktree-clean.timer; do
	ln -sfn "$script_dir/../systemd/$unit" "$HOME/.config/systemd/user/$unit"
done
systemctl --user daemon-reload
systemctl --user enable --now worktree-clean.timer
