#!/usr/bin/env bash
# Reclaim disk space through the tools that own the data.
#
# Git and MBX own worktree retirement; the Python helper validates submodules
# before its narrowly scoped single-force removal. Branches are preserved.
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
      --gc        also collect MBX storage with a 25GiB object budget
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
DO_GC=0
ROOTS=()

while [ $# -gt 0 ]; do
	case "$1" in
	-n | --dry-run) DRY_RUN=1 ;;
	--targets) DO_TARGETS=1 ;;
	--gc) DO_GC=1 ;;
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
	active_cwds >"$CWDS" || return 0
	[ -s "$CWDS" ] || return 0
	grep -qxF "$path" "$CWDS" && return 0
	awk -v path="$path/" 'index($0, path) == 1 { found=1 } END { exit !found }' "$CWDS"
}

echo "clean.sh: scanning ${ROOTS[*]}"
[ "$DRY_RUN" = 1 ] && echo "clean.sh: DRY RUN, nothing will be changed"

# Scratch files are named explicitly and removed by name, so cleanup never
# recurses into anything.
TMP=$(mktemp -d)
CWDS="$TMP/cwds"
REPOS="$TMP/repos"
cleanup() { rm -f "$CWDS" "$REPOS" && rmdir "$TMP"; }
trap cleanup EXIT

active_cwds >"$CWDS"
[ -s "$CWDS" ] || {
	echo "cannot inspect process activity" >&2
	exit 1
}

START_FREE=$(free_kib)

# Repositories: a .git at or just below each root. -print -prune keeps find out
# of the object store and out of nested worktrees, which git enumerates anyway.
: >"$REPOS"
for root in "${ROOTS[@]}"; do
	[ -d "$root" ] || continue
	# Unreadable siblings (systemd-private-* under /tmp) make find exit 1,
	# which pipefail would turn into a silent abort of the whole script.
	{ find "$root" -maxdepth 3 -name .git -print -prune 2>/dev/null || true; } |
		sed 's#/\.git$##' >>"$REPOS"
done
sort -u -o "$REPOS" "$REPOS"

echo
echo "== worktrees"
script_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
args=()
[ "$DRY_RUN" = 0 ] || args+=(--dry-run)
[ "$DO_GC" = 0 ] || args+=(--gc)
for root in "${ROOTS[@]}"; do args+=(--root "$root"); done
python3 "$script_dir/clean-worktrees.py" "${args[@]}"

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
		if [ -L "$repo/target" ]; then
			echo "  skip: $repo/target (MBX-managed; use just clean in the checkout)"
			continue
		fi
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
END_FREE=$(free_kib)
echo
echo "== free space"
if [ "$DRY_RUN" = 1 ]; then
	echo "  dry run: free space unchanged ($(human "$END_FREE") free)"
else
	echo "  $(human "$END_FREE") free; net change $(human $((END_FREE - START_FREE))) (includes other processes)"
fi
