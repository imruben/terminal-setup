#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · installer
#  Ubuntu 24.04 / 26.04 (also in WSL) and macOS. Run it again at any time: it only
#  does what is still missing, and when it is installed already it also runs `update`
#  (packages and plugins to their latest versions).
#
#    ./install.sh              shows the plan, asks, installs
#    ./install.sh --yes        no questions
#    ./install.sh --dry-run    only shows what it would do
#    ./install.sh --config-only only the config files (no packages, font, plugins)
#    ./install.sh --no-update  installed already: only what is missing, no `update`
#
#  1. packages (apt / Homebrew) that are missing, at the versions the setup needs
#  2. the Nerd Font
#  3. config: a line at the end of your ~/.zshrc and ~/.tmux.conf loads the repo's
#     (your files stay; ./uninstall.sh takes those lines out again)
#  4. tmux and zsh plugins (install/plugins.lock)
#  5. zsh as your login shell
#  6. installed already: `update` (zsh/functions.zsh)
#  7. a final check (install/doctor.sh)
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
USER=${USER:-$(id -un)}                    # not set in some containers
# shellcheck source=install/lib.sh
. "$REPO/install/lib.sh"
. "$REPO/install/versions.sh"
. "$REPO/install/fonts.sh"
. "$REPO/install/plugins.sh"
. "$REPO/install/config.sh"

ASSUME_YES=0 DRY_RUN=0 CONFIG_ONLY=0 NO_UPDATE=0
for arg in "$@"; do
  case $arg in
    -y|--yes)     ASSUME_YES=1 ;;
    -n|--dry-run) DRY_RUN=1 ;;
    --config-only|--links-only) CONFIG_ONLY=1 ;;
    --no-update)  NO_UPDATE=1 ;;
    -h|--help)    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            die "unknown option: $arg (see ./install.sh --help)" ;;
  esac
done
BACKUP_DIR="$HOME/.terminal-setup-backup/$(date +%Y%m%d-%H%M%S)"
case $REPO in *[[:space:]]*) die "the repo's path has spaces ($REPO): clone it somewhere without them" ;; esac

login_shell_zsh() {
  local zsh_path current
  zsh_path=$(command -v zsh || true)
  [ -n "$zsh_path" ] || { warn "zsh is not installed: skipped"; return; }
  if [ "$OS" = macos ]; then
    current=$(dscl . -read "/Users/$USER" UserShell 2>/dev/null | awk '{print $2}' || true)
  else
    current=$(getent passwd "$USER" | cut -d: -f7 || true)
  fi
  case $current in */zsh) ok "zsh is already your login shell"; return ;; esac
  step "Login shell"
  if ask "Make zsh your login shell? (now: ${current:-unknown})"; then
    grep -qx "$zsh_path" /etc/shells || as_root sh -c "echo '$zsh_path' >> /etc/shells"
    as_root chsh -s "$zsh_path" "$USER" || warn "chsh failed: run  chsh -s $zsh_path  yourself"
    ok "zsh from the next login"
  fi
}

# installed already (both files load the repo): this run also updates everything
UPDATE=0
if [ "$CONFIG_ONLY" = 0 ] && [ "$NO_UPDATE" = 0 ] && has_block "$HOME/.zshrc" && has_block "$HOME/.tmux.conf"; then
  UPDATE=1
fi

# ─── plan ───
detect_platform
printf '\n%sterminal-setup%s · %s · %s\n' "$B" "$R" "$OS_NAME" "$ARCH"
printf '%s%s%s\n' "$D" "repo: $(tilde "$REPO")" "$R"
[ "$DRY_RUN" = 1 ] && printf '%s(dry run: nothing is changed)%s\n' "$YELLOW" "$R"

case "$OS:$OS_VERSION" in
  ubuntu:24.04|ubuntu:26.04|macos:*) ;;
  ubuntu:*) warn "Ubuntu $OS_VERSION is not tested (24.04 and 26.04 are): going on with apt" ;;
  *)        [ "$CONFIG_ONLY" = 1 ] || die "$OS_NAME is not supported (Ubuntu 24.04 / 26.04, WSL, macOS). ./install.sh --config-only sets up the config anyway." ;;
esac

if [ "$CONFIG_ONLY" = 0 ]; then
  step "Plan"
  if [ "$OS" = macos ]; then
    . "$REPO/install/brew.sh"; brew_plan; brew_show_plan
  else
    . "$REPO/install/apt.sh"; apt_plan; apt_show_plan
  fi
  font_plan; font_show_plan
  plugins_plan; plugins_show_plan
fi
info "config: one line at the end of ~/.zshrc and of ~/.tmux.conf loads the repo's"
info "${D}(your files stay as they are; a copy of each goes to $(tilde "$BACKUP_DIR"))${R}"
[ "$UPDATE" = 1 ] && info "installed already: then ${B}update${R}, packages and plugins to their latest versions"
[ -n "$(links_into_repo)" ] && info "an install from before (links into the repo) becomes plain files: $(links_into_repo | sed 's|^|~/|' | tr '\n' ' ')"

ask "Go ahead?" || { info "nothing changed"; exit 0; }

# ─── do it ───
if [ "$CONFIG_ONLY" = 0 ]; then
  if [ "$OS" = macos ]; then brew_install; else apt_install; fi
  font_install
fi
configure
[ "$CONFIG_ONLY" = 0 ] && plugins_install
[ "$CONFIG_ONLY" = 0 ] && login_shell_zsh

if [ "$UPDATE" = 1 ]; then
  step "Update (packages and plugins to their latest versions)"
  if [ "$DRY_RUN" = 1 ]; then
    info "[dry-run] update  (zsh/functions.zsh)"
  else
    # functions.zsh returns non-zero at its end (a hook test): only `update` counts
    TERMINAL_SETUP=$REPO zsh -c '. "$TERMINAL_SETUP/zsh/functions.zsh"; update' \
      || warn "update finished with errors (see above)"
  fi
fi

# a running tmux picks up the new config
# shellcheck disable=SC2033  # tmux's own info command, not our info()
if [ "$DRY_RUN" = 0 ] && tmux info >/dev/null 2>&1; then
  tmux source-file "$HOME/.tmux.conf" >/dev/null 2>&1 && ok "the running tmux reloaded its config"
  # its monitor still runs the code it started with (or, after a migration, the scripts where
  # the old links pointed): build it again, on the tab you were on
  if tmux has-session -t system 2>/dev/null; then
    "$REPO/tmux/system.sh" restart >/dev/null 2>&1 && ok "system monitor rebuilt with this version"
  fi
fi

doctor_rc=0
if [ "$DRY_RUN" = 0 ]; then
  step "Check"
  bash "$REPO/install/doctor.sh" || doctor_rc=$?
fi

[ "${FONT_TODO:-}" = windows ] && font_windows_steps
[ -d "$BACKUP_DIR" ] && printf '\n    A copy of your files as they were: %s\n' "$(tilde "$BACKUP_DIR")"
cat <<EOF

    ${B}Done.${R} Open a new terminal (or run: exec zsh). tmux starts by itself in the
    system monitor; Ctrl+a ? shows every shortcut, Ctrl+a Space the quick menu.

EOF
exit "$doctor_rc"            # the check found problems: scripts (make install YES=1) can tell
