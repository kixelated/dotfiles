#!/usr/bin/env bash

# Load the development environment captured by a repository's reviewed Codex
# SessionStart hook.
project_dir="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
env_file="$project_dir/.direnv/codex-env.sh"

if [ -r "$env_file" ]; then
	# shellcheck disable=SC1090
	source "$env_file"
fi
