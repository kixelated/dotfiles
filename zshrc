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

source "$HOME/.kixelated.shellrc"

[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"

[ -s "$BUN_INSTALL/_bun" ] && source "$BUN_INSTALL/_bun"

command -v direnv >/dev/null && eval "$(direnv hook zsh)"
