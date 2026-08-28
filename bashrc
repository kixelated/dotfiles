# Sourced as ~/.kixelated.bashrc from the machine-local ~/.bashrc (see install).

source "$HOME/.kixelated.shellenv"
source "$HOME/.kixelated.shellrc"

# Vi mode on the command line.
set -o vi

[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"

command -v direnv >/dev/null && eval "$(direnv hook bash)"
