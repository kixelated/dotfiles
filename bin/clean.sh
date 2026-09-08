#!/usr/bin/env bash
# Reclaim disk space through the tools that own the data.
#
# This script never deletes anything itself: no rm, no find -delete, no trash.
# Every removal goes through git, cargo, or nix. When one of those refuses, that
# is the answer, not an obstacle to route around, so nothing here passes
# --force. Branches are never deleted; only the checkouts pointing at them.
set -euo pipefail

usage() {
	cat <<'USAGE'
usage: clean.sh [options]

Removes stale git worktrees, then optionally reclaims build output and the Nix
store. A worktree is removed only when it is registered, unlocked, not the main
checkout, clean including untracked files, has no process running inside it, and
either its branch is merged into the base or its upstream is gone (detached
HEADs additionally need their commit reachable from some surviving ref).

options:
  -n, --dry-run   report what would happen and change nothing
      --targets   also run `cargo clean` on build output in retained checkouts
      --nix       also run `nix store gc` (skipped when a Nix session is live)
      --all       --targets --nix
      --root DIR  search DIR for repositories (repeatable; default ~/work, /tmp)
  -h, --help      this message
USAGE
}

DRY_RUN=0
DO_TARGETS=0
DO_NIX=0
ROOTS=()

while [ $# -gt 0 ]; do
	case "$1" in
	-n | --dry-run) DRY_RUN=1 ;;
	--targets) DO_TARGETS=1 ;;
	--nix) DO_NIX=1 ;;
	--all)
		DO_TARGETS=1
		DO_NIX=1
		;;
	--root)
		[ $# -ge 2 ] || {
			echo "clean.sh: --root needs a directory" >&2
			exit 2
		}
		ROOTS+=("$2")
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "clean.sh: unknown argument: $1" >&2
		usage >&2
		exit 2
		;;
	esac
	shift
done

[ ${#ROOTS[@]} -gt 0 ] || ROOTS=("$HOME/work" "$HOME/.codex/worktrees" /tmp)

# Resolve roots, because find does not descend through a symlinked argument and
# /tmp is one on macOS, which would silently scan nothing.
for i in "${!ROOTS[@]}"; do
	if resolved=$(cd "${ROOTS[$i]}" 2>/dev/null && pwd -P); then
		ROOTS[i]=$resolved
	fi
done

run() {
	if [ "$DRY_RUN" = 1 ]; then
		echo "    would run: $*"
		return 0
	fi
	"$@"
}

free_kib() { df -k / | awk 'NR==2 {print $4}'; }

human() { awk -v k="$1" 'BEGIN { printf "%.1f GB", k / 1048576 }'; }

# Every directory some live process is sitting in. A worktree containing one is
# assumed to be in use; a missing signal is never read as "idle".
active_cwds() {
	lsof -n -a -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | sort -u
}

is_active() {
	local path=$1
	grep -qxF "$path" "$CWDS" && return 0
	grep -q "^${path}/" "$CWDS"
}

# The upstream default branch, so "merged" means merged somewhere real. A repo
# with no origin yields an empty base, and then nothing counts as merged.
base_ref() {
	local repo=$1 ref
	for ref in refs/remotes/origin/HEAD refs/remotes/origin/main refs/remotes/origin/master; do
		if git -C "$repo" rev-parse --verify --quiet "$ref" >/dev/null; then
			echo "$ref"
			return 0
		fi
	done
}

# Why this worktree must be kept, or nothing at all when it can go.
keep_reason() {
	local repo=$1 wt=$2 branch=$3 locked=$4 is_main=$5 base=$6

	[ "$is_main" = 1 ] && {
		echo "main checkout"
		return
	}
	[ "$locked" = 1 ] && {
		echo "locked"
		return
	}
	[ -d "$wt" ] || {
		echo "missing (prunable)"
		return
	}
	if [ -n "$(git -C "$wt" status --porcelain 2>&1)" ]; then
		echo "uncommitted or untracked files"
		return
	fi
	if is_active "$wt"; then
		echo "a process is running inside it"
		return
	fi

	local head
	head=$(git -C "$wt" rev-parse HEAD)

	if [ -z "$branch" ]; then
		# Detached: the commit has to survive somewhere once the checkout is gone.
		if [ -z "$(git -C "$repo" for-each-ref --contains "$head" --count=1 refs/heads refs/tags refs/remotes)" ]; then
			echo "detached at a commit no ref contains"
			return
		fi
		return
	fi

	if [ -n "$base" ] && git -C "$repo" merge-base --is-ancestor "$head" "$base" 2>/dev/null; then
		return
	fi
	# A branch that was pushed and whose remote ref has since disappeared is
	# finished work: the commits are on the branch either way, but the checkout
	# has nothing left to track.
	if git -C "$repo" config --get "branch.${branch}.remote" >/dev/null &&
		! git -C "$wt" rev-parse --verify --quiet '@{upstream}' >/dev/null; then
		return
	fi
	echo "unmerged"
}

echo "clean.sh: scanning ${ROOTS[*]}"
[ "$DRY_RUN" = 1 ] && echo "clean.sh: DRY RUN, nothing will be changed"

# Scratch files are named explicitly and removed by name, so cleanup never
# recurses into anything.
TMP=$(mktemp -d)
CWDS="$TMP/cwds"
REPOS="$TMP/repos"
KEPT="$TMP/kept"
SEEN="$TMP/seen"
cleanup() { rm -f "$CWDS" "$REPOS" "$KEPT" "$SEEN" && rmdir "$TMP"; }
trap cleanup EXIT

active_cwds >"$CWDS"

START_FREE=$(free_kib)

# Repositories: a .git at or just below each root. -print -prune keeps find out
# of the object store and out of nested worktrees, which git enumerates anyway.
: >"$REPOS"
for root in "${ROOTS[@]}"; do
	[ -d "$root" ] || continue
	find "$root" -maxdepth 3 -name .git -print -prune 2>/dev/null |
		sed 's#/\.git$##' >>"$REPOS"
done
sort -u -o "$REPOS" "$REPOS"

: >"$KEPT"
: >"$SEEN"

echo
echo "== worktrees"
while IFS= read -r repo; do
	common=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || continue
	grep -qxF "$common" "$SEEN" && continue
	echo "$common" >>"$SEEN"

	base=$(base_ref "$repo")
	main_wt=1
	wt=""
	branch=""
	locked=0

	# --porcelain emits a blank-line-separated record per worktree; the trailing
	# newline below flushes the last one.
	while IFS= read -r line; do
		case "$line" in
		"worktree "*)
			wt=${line#worktree }
			branch=""
			locked=0
			;;
		"branch "*) branch=${line#branch refs/heads/} ;;
		"locked"*) locked=1 ;;
		"")
			[ -n "$wt" ] || continue
			reason=$(keep_reason "$repo" "$wt" "$branch" "$locked" "$main_wt" "$base")
			main_wt=0
			if [ -n "$reason" ]; then
				printf '%s\t%s\n' "$wt" "$reason" >>"$KEPT"
			else
				echo "  remove: $wt [${branch:-detached}]"
				if ! run git -C "$repo" worktree remove "$wt"; then
					echo "    kept: git refused"
				fi
			fi
			wt=""
			;;
		esac
	done < <(git -C "$repo" worktree list --porcelain 2>/dev/null; echo)

	# Registrations whose directory is already gone. Prune only once every entry
	# git lists is confirmed absent, so a temporarily unmounted checkout survives.
	stale=$(git -C "$repo" worktree prune --dry-run --verbose 2>&1)
	if [ -n "$stale" ]; then
		unsafe=0
		while IFS= read -r entry; do
			[ -n "$entry" ] || continue
			case "$entry" in
			*"points to non-existent location"*) ;;
			*) unsafe=1 ;;
			esac
		done <<<"$stale"
		if [ "$unsafe" = 0 ]; then
			echo "  prune stale registrations in $repo"
			run git -C "$repo" worktree prune
		else
			echo "  kept: unrecognized prune reason in $repo"
			printf '    %s\n' "$stale"
		fi
	fi
done <"$REPOS"

if [ "$DO_TARGETS" = 1 ]; then
	echo
	echo "== build output (cargo clean)"
	# A retained checkout's target/ is reproducible, so it can go even when the
	# checkout itself must stay. Skip anything with a process inside: that is
	# very likely the build writing into it.
	manifest=""
	while IFS= read -r repo; do
		[ -f "$repo/Cargo.toml" ] || continue
		[ -n "$manifest" ] || manifest="$repo/Cargo.toml"
		[ -d "$repo/target" ] || continue
		if is_active "$repo"; then
			echo "  skip: $repo/target (process running inside)"
			continue
		fi
		# --target-dir is explicit because a config.toml (mbx, sccache, a shared
		# cache) can redirect the default elsewhere, and clearing a cache shared
		# with live builds is not what was asked for.
		echo "  cargo clean: $repo/target"
		run cargo clean --quiet --manifest-path "$repo/Cargo.toml" \
			--target-dir "$repo/target" || echo "    kept: cargo refused"
	done <"$REPOS"

	# Target directories left behind in a scratch root by a checkout that is
	# already gone. Cargo needs some manifest to run at all, but only ever
	# touches the directory named by --target-dir, so any real one will do.
	if [ -n "$manifest" ]; then
		for root in "${ROOTS[@]}"; do
			[ -d "$root" ] || continue
			while IFS= read -r tag; do
				orphan=$(dirname "$tag")
				[ -f "$orphan/.rustc_info.json" ] || continue
				if is_active "$orphan"; then
					echo "  skip: $orphan (process running inside)"
					continue
				fi
				echo "  cargo clean: $orphan (orphaned target dir)"
				run cargo clean --quiet --manifest-path "$manifest" \
					--target-dir "$orphan" || echo "    kept: cargo refused"
			done < <(find "$root" -maxdepth 2 -name CACHEDIR.TAG 2>/dev/null)
		done
	fi
fi

if [ "$DO_NIX" = 1 ]; then
	echo
	echo "== nix store"
	if ! command -v nix >/dev/null; then
		echo "  skip: nix is not installed"
	elif pgrep -qf '/tmp/nix-shell\.' || pgrep -qf 'nix (build|develop|shell)' ||
		pgrep -qx nix-build >/dev/null 2>&1; then
		# The daemon is always resident and does not count; a live build or
		# devshell does, since collecting out from under it breaks it.
		echo "  skip: a nix build or devshell is running"
	else
		echo "  nix store gc (collected paths will be re-downloaded when next built)"
		run nix store gc
	fi
fi

echo
echo "== kept"
if [ -s "$KEPT" ]; then
	sort "$KEPT" | while IFS=$'\t' read -r wt reason; do
		printf '  %-70s %s\n' "$wt" "$reason"
	done
else
	echo "  nothing"
fi

END_FREE=$(free_kib)
echo
echo "== reclaimed"
if [ "$DRY_RUN" = 1 ]; then
	echo "  dry run: free space unchanged ($(human "$END_FREE") free)"
else
	echo "  $(human $((END_FREE - START_FREE))) freed, $(human "$END_FREE") now free"
fi
