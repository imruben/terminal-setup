# ═══════════════════════════════════════════════════════════════
#  terminal-setup · WSL: Linux plus the Windows integration.
#  Windows apps are called by their full path: they are not on $PATH when
#  /etc/wsl.conf has appendWindowsPath=false (keeps the shell fast).
# ═══════════════════════════════════════════════════════════════

source "$TERMINAL_SETUP/zsh/platform/linux.zsh"       # open (→ Windows Explorer / browser here), clipboard, ssh-agent

# a terminal opened from Windows may start in /mnt/c/…: home is nicer (and much faster).
# Only that first shell: a pane or shell you open in a /mnt/c folder stays there.
[[ -z $TMUX && $SHLVL == 1 && $PWD == /mnt/c/* ]] && cd ~
