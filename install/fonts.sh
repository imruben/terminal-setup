# shellcheck shell=bash
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · the Nerd Font ("JetBrainsMono Nerd Font"): the icons of the
#  prompt, the tmux bar and the panels are drawn with it. It must be installed
#  where the terminal window is drawn:
#    macOS            the Brewfile installs it (cask font-jetbrains-mono-nerd-font)
#    Linux desktop    ~/.local/share/fonts (downloaded from the Nerd Fonts release)
#    WSL              in Windows: checked, and explained when it is missing
#    server over SSH  on the computer you connect from: nothing to do here
# ═══════════════════════════════════════════════════════════════

# (no `… | grep -q`: under install.sh's pipefail the writer's SIGPIPE would count as "missing")
font_present_linux() { grep -qi "JetBrainsMono Nerd Font" <<< "$(fc-list 2>/dev/null)"; }
# the Homebrew cask puts the .ttf files in ~/Library/Fonts
font_present_macos() { grep -qi "JetBrainsMonoNerdFont" <<< "$(printf '%s\n' ~/Library/Fonts/* /Library/Fonts/*)"; }

font_present_windows() {
  local d c
  # C: wherever WSL mounts it (/mnt/c, or another automount root in /etc/wsl.conf)
  c=$(wslpath -u 'C:\' 2>/dev/null); c=${c%/}; c=${c:-/mnt/c}
  for d in "$c"/Windows/Fonts "$c"/Users/*/AppData/Local/Microsoft/Windows/Fonts; do
    grep -qi "JetBrainsMonoNerdFont" <<< "$(printf '%s\n' "$d"/*)" && return 0
  done
  return 1
}

font_plan() {
  FONT_TODO=none
  case "$OS:$IS_WSL" in
    macos:*) font_present_macos || FONT_TODO=macos ;;           # the Brewfile installs it
    *:1)     font_present_windows || FONT_TODO=windows ;;
    *)       if [ "$HAS_DESKTOP" = 1 ]; then font_present_linux || FONT_TODO=linux; else FONT_TODO=remote; fi ;;
  esac
}

font_show_plan() {
  case $FONT_TODO in
    linux)   info "font: JetBrainsMono Nerd Font $NERD_FONT_VERSION → ~/.local/share/fonts" ;;
    windows) info "font: JetBrainsMono Nerd Font is missing in Windows → steps at the end" ;;
    remote)  info "font: no desktop here → install it on the computer you connect from" ;;
    macos)   info "font: JetBrainsMono Nerd Font → with the Homebrew packages (Brewfile)" ;;
    none)    ok "font: JetBrainsMono Nerd Font is there" ;;
  esac
}

font_install() {
  [ "$FONT_TODO" = linux ] || return 0
  step "JetBrainsMono Nerd Font"
  local tmp
  tmp=$(mktemp -d)
  download "https://github.com/ryanoasis/nerd-fonts/releases/download/$NERD_FONT_VERSION/$NERD_FONT.zip" \
    "$tmp/font.zip" font
  run mkdir -p ~/.local/share/fonts/JetBrainsMonoNerdFont
  run unzip -oq "$tmp/font.zip" '*.ttf' -d ~/.local/share/fonts/JetBrainsMonoNerdFont
  run fc-cache -f
  rm -rf "$tmp"
  ok "installed · choose \"JetBrainsMono Nerd Font\" in your terminal's settings"
}

# the steps for Windows, shown at the end of the install
font_windows_steps() {
  cat <<EOF

    ${B}The font goes in Windows${R} (Windows Terminal draws the text). In PowerShell:

        winget install --id DEVCOM.JetBrainsMonoNerdFont

    or download https://github.com/ryanoasis/nerd-fonts/releases/download/$NERD_FONT_VERSION/$NERD_FONT.zip,
    unzip it, select the .ttf files › right-click › Install for all users.
    Then in Windows Terminal: Settings › your Ubuntu profile › Appearance ›
    Font face: ${B}JetBrainsMono Nerd Font${R} (more in windows/windows-terminal.md).
EOF
}
