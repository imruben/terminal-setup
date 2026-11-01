# ═══════════════════════════════════════════════════════════════
#  terminal-setup · WSL: Linux plus the Windows integration.
#  Windows apps are called by their full path: they are not on $PATH when
#  /etc/wsl.conf has appendWindowsPath=false (keeps the shell fast).
# ═══════════════════════════════════════════════════════════════

source "${0:A:h}/linux.zsh"       # open (→ Windows Explorer / browser here), clipboard, ssh-agent

# a terminal opened from Windows may start in /mnt/c/…: home is nicer (and much faster).
# Only that first shell: a pane or shell you open in a /mnt/c folder stays there.
[[ -z $TMUX && $SHLVL == 1 && $PWD == /mnt/c/* ]] && cd ~

# VS Code: `code .` opens the folder through VS Code's WSL bridge.
# Found on first use (user or system install), so startup never touches /mnt/c.
code() {
  local bin
  for bin in /mnt/c/Users/*/AppData/Local/Programs/"Microsoft VS Code"/bin/code(N) \
             "/mnt/c/Program Files/Microsoft VS Code/bin/code"(N); do
    "$bin" "$@"; return
  done
  print -u2 "code: VS Code not found under /mnt/c (install it on Windows)"; return 1
}
