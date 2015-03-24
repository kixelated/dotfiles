execute pathogen#infect()
syntax on
filetype plugin indent on

set nocompatible

set background=dark     " dark background
colorscheme desert      " colorscheme desert

set history=9999
set timeoutlen=300

set backup
set backupdir=~/.vim/backup
set directory=~/.vim/temp

set number              " line numbers
set noerrorbells

set autoindent          " auto indenting
set backspace=indent,eol,start
set shiftwidth=4
set softtabstop=4
set tabstop=4
"set expandtab
"set cindent

set incsearch
set hlsearch
set showmatch
set ignorecase
set infercase

set wrap
set linebreak
set nolist

set shiftround
set smartcase

set pastetoggle=<f11>

set wildmenu
set wildignore=*.dll,*.o,*.obj,*.bak,*.exe,*.pyc,*.jpg,*.gif,*.png
set wildmode=list:longest
au FileType gitcommit set tw=72

map <f6> :w <CR>:!bash % <CR>

highlight ExtraWhitespace ctermbg=darkgreen guibg=darkgreen
au ColorScheme * highlight ExtraWhitespace guibg=darkgreen
au BufEnter * match ExtraWhitespace /\s\+$/
au InsertEnter * match ExtraWhitespace /\s\+\%#\@<!$/
au InsertLeave * match ExtraWhiteSpace /\s\+$/

" inoremap # X#
if has("autocmd")
  au BufReadPost * if line("'\"") > 0 && line("'\"") <= line("$")
    \| exe "normal! g'\"" | endif
endif

autocmd BufRead,BufNewFile *.as set filetype=as3
