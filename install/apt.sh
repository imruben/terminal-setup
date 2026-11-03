# shellcheck shell=bash
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · packages on Ubuntu 24.04 / 26.04 (also inside WSL)
#  Only what is missing is installed. What Ubuntu's own version cannot do is
#  fetched at the version this setup was tested with (install/versions.sh):
#    tmux       ≥ 3.6   24.04 has 3.4      → built from source (install/tmux-build.sh)
#    fzf        ≥ 0.48  24.04 has 0.44     → official binary in ~/.local/bin
#    fastfetch          not in 24.04       → official .deb
#    starship           not in 24.04       → official installer, in ~/.local/bin
#    lazygit            not in 24.04       → official binary in ~/.local/bin
#    yq                 Ubuntu's "yq" is another program (a Python jq wrapper)
#                                          → mikefarah/yq's official binary in ~/.local/bin
# ═══════════════════════════════════════════════════════════════

# what the setup uses (Ubuntu package names)
APT_PACKAGES="zsh git curl ca-certificates python3 jq eza bat micro btop entr ansifilter git-delta
  zsh-autosuggestions zsh-syntax-highlighting fontconfig unzip iproute2 psmisc procps lsof
  ripgrep fd-find zoxide tealdeer shellcheck"
# a clipboard tool for pbcopy / pbpaste where there is a desktop (WSLg counts)
APT_DESKTOP="wl-clipboard"

# apt-get without its screens of dpkg output: kept in a log, shown only when it fails
# (sudo drops DEBIAN_FRONTEND, so it is passed explicitly)
APT_LOG=${TMPDIR:-/tmp}/terminal-setup-apt.log
apt_get() {
  if [ "${DRY_RUN:-0}" = 1 ]; then run apt-get "$@"; return; fi
  if [ "$(id -u)" = 0 ]; then set -- env DEBIAN_FRONTEND=noninteractive apt-get -y -q "$@"
  else set -- sudo env DEBIAN_FRONTEND=noninteractive apt-get -y -q "$@"; fi
  "$@" >"$APT_LOG" 2>&1 || { tail -20 "$APT_LOG" >&2; die "apt-get failed (full log: $APT_LOG)"; }
}

apt_candidate() { apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ {print $2}' | sed 's/(none)//; s/^[0-9]*://'; }
apt_installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q " installed$"; }

# The plan needs the package lists to know what Ubuntu offers: only a fresh system has none,
# and only then they are fetched before you said yes. Lists older than a day are refreshed
# after it, before installing. (pkgcache.bin is rebuilt on every update; the lists keep the
# server's dates, not the download's)
apt_has_lists()     { [ -n "$(find /var/lib/apt/lists -maxdepth 1 -name '*_Packages' 2>/dev/null | head -1)" ]; }
apt_lists_recent()  { [ -n "$(find /var/cache/apt/pkgcache.bin -mmin -1440 2>/dev/null)" ]; }
apt_refresh_lists() {
  apt_has_lists && return
  info "no package lists yet: fetching them first to plan (apt-get update, asks for your password)…"
  apt_get update
}

apt_plan() {
  APT_MISSING="" NEED_TMUX_BUILD=0 NEED_FZF=0 NEED_FASTFETCH=0 NEED_STARSHIP=0 NEED_LAZYGIT=0 NEED_YQ=0
  apt_refresh_lists
  local p list=$APT_PACKAGES
  { [ "$HAS_DESKTOP" = 1 ] || [ "$IS_WSL" = 1 ]; } && list="$list $APT_DESKTOP"
  for p in $list; do apt_installed "$p" || APT_MISSING="$APT_MISSING $p"; done
  # tmux: Ubuntu's when it is new enough, else built from source
  if ! { have tmux && version_ge "$(tmux -V)" "$TMUX_MIN"; }; then
    if version_ge "$(apt_candidate tmux)" "$TMUX_MIN"; then APT_MISSING="$APT_MISSING tmux"; else NEED_TMUX_BUILD=1; fi
  fi
  if ! { have fzf && version_ge "$(fzf --version | awk '{print $1}')" "$FZF_MIN"; }; then
    if version_ge "$(apt_candidate fzf)" "$FZF_MIN"; then APT_MISSING="$APT_MISSING fzf"; else NEED_FZF=1; fi
  fi
  if ! have fastfetch; then
    if [ -n "$(apt_candidate fastfetch)" ]; then APT_MISSING="$APT_MISSING fastfetch"; else NEED_FASTFETCH=1; fi
  fi
  if ! have starship; then
    if [ -n "$(apt_candidate starship)" ]; then APT_MISSING="$APT_MISSING starship"; else NEED_STARSHIP=1; fi
  fi
  if ! have lazygit; then
    if [ -n "$(apt_candidate lazygit)" ]; then APT_MISSING="$APT_MISSING lazygit"; else NEED_LAZYGIT=1; fi
  fi
  have_mikefarah_yq || NEED_YQ=1
}
# the yq of Homebrew, snap and every guide (Go, mikefarah): not Ubuntu's Python one
have_mikefarah_yq() { have yq && yq --version 2>&1 | grep -q mikefarah; }

apt_show_plan() {
  [ -n "$APT_MISSING" ] && info "apt install:${APT_MISSING}" || ok "every apt package is there"
  [ "$NEED_TMUX_BUILD" = 1 ] && info "tmux $TMUX_VERSION: built from source (Ubuntu's is older than $TMUX_MIN)"
  [ "$NEED_FZF" = 1 ] && info "fzf $FZF_VERSION: official binary in ~/.local/bin (Ubuntu's is older than $FZF_MIN)"
  [ "$NEED_FASTFETCH" = 1 ] && info "fastfetch $FASTFETCH_VERSION: official .deb (not in this Ubuntu)"
  [ "$NEED_STARSHIP" = 1 ] && info "starship: official installer, in ~/.local/bin (not in this Ubuntu)"
  [ "$NEED_LAZYGIT" = 1 ] && info "lazygit $LAZYGIT_VERSION: official binary in ~/.local/bin (not in this Ubuntu)"
  [ "$NEED_YQ" = 1 ] && info "yq $YQ_VERSION: official binary in ~/.local/bin (Ubuntu's yq is a different program)"
  return 0
}

apt_install() {
  export DEBIAN_FRONTEND=noninteractive
  step "Ubuntu packages"
  if [ -n "$APT_MISSING" ] && ! apt_lists_recent; then
    info "refreshing the package lists (apt-get update)…"
    apt_get update
  fi
  case "$APT_MISSING$NEED_TMUX_BUILD$NEED_FZF$NEED_FASTFETCH$NEED_STARSHIP$NEED_LAZYGIT$NEED_YQ" in
    000000) ok "nothing to install: every package is there" ;;
  esac
  if [ -n "$APT_MISSING" ]; then
    info "installing $(printf '%s\n' $APT_MISSING | wc -l | tr -d ' ') packages (a few minutes)…"
    # shellcheck disable=SC2086
    apt_get install $APT_MISSING
    ok "apt packages installed"
  fi
  local tmp
  tmp=$(mktemp -d)
  if [ "$NEED_TMUX_BUILD" = 1 ]; then
    # shellcheck source=install/tmux-build.sh
    . "$REPO/install/tmux-build.sh"
    tmux_build
  fi
  if [ "$NEED_FZF" = 1 ]; then
    run curl -fsSL -o "$tmp/fzf.tgz" \
      "https://github.com/junegunn/fzf/releases/download/v$FZF_VERSION/fzf-$FZF_VERSION-linux_$ARCH.tar.gz"
    run mkdir -p ~/.local/bin
    run tar -xzf "$tmp/fzf.tgz" -C ~/.local/bin fzf
    ok "fzf $FZF_VERSION in ~/.local/bin"
  fi
  if [ "$NEED_FASTFETCH" = 1 ]; then
    local ffarch=$ARCH; [ "$ARCH" = arm64 ] && ffarch=aarch64
    run curl -fsSL -o "$tmp/fastfetch.deb" \
      "https://github.com/fastfetch-cli/fastfetch/releases/download/$FASTFETCH_VERSION/fastfetch-linux-$ffarch.deb"
    apt_get install "$tmp/fastfetch.deb"
    ok "fastfetch $FASTFETCH_VERSION"
  fi
  if [ "$NEED_STARSHIP" = 1 ]; then
    run mkdir -p ~/.local/bin
    # downloaded first: piped into sh, a failed download would look like a good install
    run curl -fsSL -o "$tmp/starship-install.sh" https://starship.rs/install.sh
    run sh -c "sh '$tmp/starship-install.sh' -y -b '$HOME/.local/bin' >/dev/null"
    ok "starship in ~/.local/bin"
  fi
  if [ "$NEED_LAZYGIT" = 1 ]; then
    local lgarch=x86_64; [ "$ARCH" = arm64 ] && lgarch=arm64
    run curl -fsSL -o "$tmp/lazygit.tgz" \
      "https://github.com/jesseduffield/lazygit/releases/download/v$LAZYGIT_VERSION/lazygit_${LAZYGIT_VERSION}_linux_$lgarch.tar.gz"
    run mkdir -p ~/.local/bin
    run tar -xzf "$tmp/lazygit.tgz" -C ~/.local/bin lazygit
    ok "lazygit $LAZYGIT_VERSION in ~/.local/bin"
  fi
  if [ "$NEED_YQ" = 1 ]; then
    run mkdir -p ~/.local/bin
    run curl -fsSL -o "$tmp/yq" "https://github.com/mikefarah/yq/releases/download/v$YQ_VERSION/yq_linux_$ARCH"
    run install -m 755 "$tmp/yq" ~/.local/bin/yq
    ok "yq $YQ_VERSION in ~/.local/bin"
  fi
  rm -rf "$tmp"
  # Ubuntu calls bat "batcat" and fd "fdfind": the setup (and you) can call them bat and fd
  if ! have bat && have batcat; then
    run mkdir -p ~/.local/bin
    run ln -sf "$(command -v batcat)" ~/.local/bin/bat
    ok "bat → batcat (~/.local/bin/bat)"
  fi
  if ! have fd && have fdfind; then
    run mkdir -p ~/.local/bin
    run ln -sf "$(command -v fdfind)" ~/.local/bin/fd
    ok "fd → fdfind (~/.local/bin/fd)"
  fi
  # tldr's pages are downloaded apart from the program (later: `update` refreshes them)
  if have tldr && [ "${DRY_RUN:-0}" = 0 ]; then
    tldr --update >/dev/null 2>&1 && ok "tldr pages downloaded" || warn "tldr --update failed: run it later"
  fi
}
