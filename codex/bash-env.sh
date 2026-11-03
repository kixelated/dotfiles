#!/usr/bin/env bash

# Codex sources this through BASH_ENV in every shell command, so it loads the
# dev shell snapshot that the SessionStart hook (bin/dev-shell-hook codex)
# captured for the checkout.
#
# Load it in every bash, nested ones included. Codex runs each command as
# `bash -c '. <shell snapshot>; exec bash -c <command>'`, and its shell snapshot
# restores PATH after the outer bash loaded this, so only the inner bash
# reloading it puts the dev shell back in front.
project_dir="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
env_file="$project_dir/.direnv/codex-env.sh"

if [ -r "$env_file" ]; then
	# shellcheck disable=SC1090
	source "$env_file"
fi
