" Minimal config; vim is just the fallback editor these days.
syntax on
filetype plugin indent on

set number
set backspace=indent,eol,start
set nobackup noswapfile
set noexpandtab tabstop=4 shiftwidth=4
set incsearch hlsearch ignorecase smartcase
set wrap linebreak
set wildmenu wildmode=list:longest
set mouse=a
autocmd FileType gitcommit setlocal textwidth=72
