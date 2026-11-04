#!/usr/bin/env bash

# Codex sources this through BASH_ENV in every shell command, so it loads the
# dev shell snapshot that the SessionStart hook (bin/dev-shell-hook codex)
# captured for the checkout.
#
# Load it in every bash, nested ones included. Codex runs each command as
# `bash -c '. <shell snapshot>; exec bash -c <command>'`, and its shell snapshot
# restores PATH after the outer bash loaded this, so only the inner bash
# reloading it puts the dev shell back in front.
[ "${IN_NIX_SHELL+x}" ] && return 0

project_dir="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
env_file="$project_dir/.direnv/codex-env.sh"
[ -r "$env_file" ] || return 0

# Keep the stamp inside the snapshot so captures replace both together.
flake_stamp='# codex-env-flake:'
for flake_file in flake.nix flake.lock; do
	flake_hash=missing
	if [ -f "$project_dir/$flake_file" ]; then
		flake_hash=$(git hash-object --no-filters -- "$project_dir/$flake_file") || return 1
	fi
	flake_stamp="$flake_stamp $flake_hash"
done
snapshot_stamp=
IFS= read -r snapshot_stamp <"$env_file" || true

if [ "$snapshot_stamp" != "$flake_stamp" ]; then
	# Fresh Bash processes cannot share an exported warning flag. The hook
	# removes this marker when it captures a new snapshot.
	if (
		set -o noclobber
		: >"$env_file.stale"
	) 2>/dev/null; then
		printf 'codex: skipping stale dev shell snapshot for %s; rerun the SessionStart hook.\n' "$project_dir" >&2
	fi
	return 0
fi

# shellcheck disable=SC1090
source "$env_file"
snapshot_status=$?
# An automatically loaded snapshot is not an explicit `nix develop`. Keep
# nested Bash processes eligible to restore it after Codex resets PATH.
unset IN_NIX_SHELL
return "$snapshot_status"
