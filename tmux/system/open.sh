#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Open a URL, file or folder with the desktop's own app, whatever the system:
#    WSL    the Windows browser / Explorer (explorer.exe by its full path: Windows
#           apps may not be on $PATH, appendWindowsPath=false in /etc/wsl.conf)
#    macOS  open
#    Linux  xdg-open
#  Used by the tmux panes (Containers, Ports), extrakto, tmux-fzf-url and zsh's `open`.
#  TMUX_OPEN_URL replaces it (tests).
# ═══════════════════════════════════════════════════════════════
target=${1:?usage: open.sh URL|PATH}
if [[ -n $TMUX_OPEN_URL ]]; then
  exec "$TMUX_OPEN_URL" "$target"
elif [[ -n $WSL_DISTRO_NAME || -e /proc/sys/fs/binfmt_misc/WSLInterop || -e /proc/sys/fs/binfmt_misc/WSLInterop-late ]]; then
  [[ -e $target ]] && target=$(wslpath -w "$target")     # a Linux path → \\wsl$\… for Windows
  # C:\Windows wherever WSL mounts C: (/mnt/c, or another automount root in /etc/wsl.conf)
  explorer=$(command -v explorer.exe) || explorer="$(wslpath -u 'C:\Windows' 2>/dev/null)/explorer.exe"
  if [[ ! -x $explorer ]]; then
    command -v wslview >/dev/null && exec wslview "$target"
    echo "open.sh: Windows' explorer.exe was not found" >&2; exit 1
  fi
  "$explorer" "$target"
  exit 0                                                  # explorer.exe always exits with 1
elif [[ $OSTYPE == darwin* ]]; then
  exec open "$target"
else
  exec xdg-open "$target" >/dev/null 2>&1
fi
