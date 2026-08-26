# Sourced as ~/.kixelated.zshrc from the machine-local ~/.zshrc (see install).

# oh-my-zsh, when installed.
export ZSH="$HOME/.oh-my-zsh"
if [ -d "$ZSH" ]; then
	ZSH_THEME="robbyrussell"
	plugins=(git)
	source "$ZSH/oh-my-zsh.sh"
fi

# Vi mode on the command line.
bindkey -v

# Plain tab completion, no menu cycling.
setopt noautomenu nomenucomplete

export EDITOR=vim
export GIT_EDITOR=vim
export CLICOLOR=1
export LSCOLORS=ExFxCxDxBxegedabagacad

# Resolve symlinks when changing directories.
alias cd="cd -P"
alias grep="grep --color=auto"
alias claude!="claude --dangerously-skip-permissions"

if command -v eza >/dev/null; then
	alias l='eza --group-directories-first --icons --'
	alias ll='eza -lah --group-directories-first --icons --'
	alias la='eza -a --icons --'
	alias lt='eza --tree --icons --'
fi

export PATH="$HOME/.local/bin:$PATH"

# Toolchains, each skipped when not installed.
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"

export BUN_INSTALL="$HOME/.bun"
[ -d "$BUN_INSTALL/bin" ] && export PATH="$BUN_INSTALL/bin:$PATH"
[ -s "$BUN_INSTALL/_bun" ] && source "$BUN_INSTALL/_bun"

[ -s "$HOME/.deno/env" ] && . "$HOME/.deno/env"

export PNPM_HOME="$HOME/Library/pnpm"
if [ -d "$PNPM_HOME" ]; then
	case ":$PATH:" in
	*":$PNPM_HOME:"*) ;;
	*) export PATH="$PNPM_HOME:$PATH" ;;
	esac
fi

if [ -e /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]; then
	. /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
fi

command -v direnv >/dev/null && eval "$(direnv hook zsh)"

# 1Password CLI plugins.
[ -f "$HOME/.config/op/plugins.sh" ] && source "$HOME/.config/op/plugins.sh"
