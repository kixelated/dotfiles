#!/usr/bin/env bash

# Grok sources this through BASH_ENV in every shell command, so it loads the
# dev shell snapshot that the SessionStart hook (bin/dev-shell-hook grok)
# captured for the checkout.
#
# Source it from every bash, including one exec'd by an outer bash. A login
# snapshot replayed before the command can restore PATH; an inner bash sources
# BASH_ENV again and puts the dev shell back in front.
project_dir="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
env_file="$project_dir/.direnv/grok-env.sh"

if [ -r "$env_file" ]; then
	# shellcheck disable=SC1090
	source "$env_file"
fi
