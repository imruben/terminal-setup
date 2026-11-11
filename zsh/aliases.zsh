if (( $+commands[eza] )); then
  alias ls='eza --group-directories-first'
  alias ll='eza -alh --git --group-directories-first'
  alias la='eza -a --group-directories-first'
  alias l='eza --group-directories-first'
  alias lt='eza --tree --level=2 --group-directories-first'
elif [[ $OSTYPE == darwin* ]]; then
  alias ls='ls -G'
  alias ll='ls -alFhG'
  alias la='ls -AG'
  alias l='ls -CFG'
else
  alias ls='ls --color=auto'
  alias ll='ls -alFh'
  alias la='ls -A'
  alias l='ls -CF'
fi
alias grep='grep --color=auto'
alias lg='lazygit'
alias pn='pnpm'
alias uvr='uv run'
