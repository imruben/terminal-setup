# shellcheck shell=bash
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · packages on macOS, with Homebrew (install/Brewfile)
#  Homebrew itself is installed first when it is missing (it asks for your
#  password and installs Apple's Command Line Tools if needed).
# ═══════════════════════════════════════════════════════════════

brew_bin() {
  local p
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$p" ] && { echo "$p"; return; }; done
  command -v brew 2>/dev/null || true          # none: empty (set -e must not stop the plan)
}

brew_plan() {
  BREW=$(brew_bin)
  BREW_MISSING="" BREW_OLD=""
  if [ -z "$BREW" ]; then
    BREW_MISSING="(everything in install/Brewfile)"
    return
  fi
  # on PATH for the rest of the install, doctor.sh and `update` too (it may not be yet:
  # /opt/homebrew/bin is only added by your shell's config)
  eval "$("$BREW" shellenv)"
  local name kind formulae casks
  formulae=" $("$BREW" list --formula -1 2>/dev/null | tr '\n' ' ') "
  casks=" $("$BREW" list --cask -1 2>/dev/null | tr '\n' ' ') "
  # installed with Homebrew but older than the setup needs (a first install runs no `update`)
  if [[ $formulae == *" tmux "* ]] && ! version_ge "$(tmux -V 2>/dev/null)" "$TMUX_MIN"; then BREW_OLD="$BREW_OLD tmux"; fi
  if [[ $formulae == *" fzf "* ]] && ! version_ge "$(fzf --version 2>/dev/null)" "$FZF_MIN"; then BREW_OLD="$BREW_OLD fzf"; fi
  while read -r kind name _; do
    name=${name//\"/}
    case $kind in
      brew) [[ $formulae == *" $name "* ]] || BREW_MISSING="$BREW_MISSING $name" ;;
      cask) [[ $casks == *" $name "* ]] || BREW_MISSING="$BREW_MISSING $name" ;;
    esac
  done < <(grep -E '^(brew|cask) ' "$REPO/install/Brewfile" | sed 's/#.*//')
}

brew_show_plan() {
  [ -z "$BREW" ] && info "Homebrew: not installed → installed first (https://brew.sh)"
  [ -n "$BREW_OLD" ] && info "brew upgrade:$BREW_OLD (older than the setup needs)"
  if [ -n "$BREW_MISSING" ]; then info "brew install:$BREW_MISSING"; else ok "every Homebrew package is there"; fi
}

brew_install() {
  step "Homebrew packages"
  if [ -z "$BREW" ]; then
    if [ "${DRY_RUN:-0}" = 1 ]; then
      info "[dry-run] install Homebrew (https://brew.sh's install.sh)"
    else
      # --yes: Homebrew's own "Press RETURN to continue" too
      NONINTERACTIVE=$([ "${ASSUME_YES:-0}" = 1 ] && echo 1) \
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    BREW=$(brew_bin)
    [ -n "$BREW" ] || [ "${DRY_RUN:-0}" = 1 ] || die "Homebrew did not install: see the messages above"
    eval "$("${BREW:-/opt/homebrew/bin/brew}" shellenv 2>/dev/null)"
  fi
  # only what is missing: bundle would also upgrade every outdated formula of the Brewfile
  # (upgrades are `update`'s job, and --no-update means none)
  [ -n "$BREW_MISSING" ] && run env HOMEBREW_BUNDLE_NO_UPGRADE=1 "${BREW:-brew}" bundle --file="$REPO/install/Brewfile"
  # shellcheck disable=SC2086
  [ -n "$BREW_OLD" ] && run "$BREW" upgrade $BREW_OLD
  ok "Homebrew packages ready"
  macos_fixes
}

# Two things macOS needs for this setup, both for your user only:
macos_fixes() {
  local prefix tmp
  prefix=$("${BREW:-brew}" --prefix 2>/dev/null || true)
  # 1. macOS's own ncurses does not know "tmux-256color" (the terminal tmux declares), so
  #    less, vim… inside tmux would complain: add it to ~/.terminfo from Homebrew's ncurses
  if ! /usr/bin/infocmp tmux-256color >/dev/null 2>&1 && [ -x "$prefix/opt/ncurses/bin/infocmp" ]; then
    tmp=$(mktemp)
    run sh -c "'$prefix/opt/ncurses/bin/infocmp' -x tmux-256color > '$tmp' && /usr/bin/tic -x -o '$HOME/.terminfo' '$tmp'"
    rm -f "$tmp"
    ok "tmux-256color terminal description in ~/.terminfo"
  fi
  # 2. zsh asks before loading completions from group-writable folders: Homebrew's share/zsh
  #    (only that: on Intel Macs share/ is /usr/local/share, with files that are not Homebrew's)
  [ -n "$prefix" ] && [ -d "$prefix/share/zsh" ] && run chmod -R go-w "$prefix/share/zsh" 2>/dev/null || true
}
