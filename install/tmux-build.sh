# shellcheck shell=bash
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · tmux from source, for systems whose tmux is older than
#  $TMUX_MIN (Ubuntu 24.04 ships 3.4). Installs into /usr/local, which comes
#  before /usr/bin in $PATH; Ubuntu's own tmux package (if any) is left alone.
# ═══════════════════════════════════════════════════════════════

tmux_build() {
  step "tmux $TMUX_VERSION from source"
  apt_get install build-essential pkg-config bison libevent-dev libncurses-dev
  local tmp
  tmp=$(mktemp -d)
  download "https://github.com/tmux/tmux/releases/download/$TMUX_VERSION/tmux-$TMUX_VERSION.tar.gz" \
    "$tmp/tmux.tar.gz" tmux
  run tar -xzf "$tmp/tmux.tar.gz" -C "$tmp"
  info "building (about a minute)…"
  # compiler output goes to a log (shown only if the build fails)
  local log=$LOG_DIR/tmux-build.log
  mkdir -p "$LOG_DIR"
  run sh -c "cd '$tmp/tmux-$TMUX_VERSION' && ./configure --prefix=/usr/local && make -j\"\$(nproc)\"" >"$log" 2>&1 \
    || { tail -20 "$log" >&2; die "tmux did not build (full log: $log)"; }
  as_root make -C "$tmp/tmux-$TMUX_VERSION" install >>"$log" 2>&1 || die "tmux did not install (log: $log)"
  rm -rf "$tmp"
  hash -r
  ok "$(/usr/local/bin/tmux -V 2>/dev/null || echo "tmux $TMUX_VERSION") in /usr/local/bin"
}
