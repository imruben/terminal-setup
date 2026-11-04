# shellcheck shell=bash
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · tmux and zsh plugins, at the versions in install/plugins.lock
#    tmux/<name> → ~/.tmux/plugins/<name>   (tpm and the tmux plugins)
#    zsh/<name>  → ~/.zsh/plugins/<name>    (fzf-tab)
#  A missing plugin is cloned and set to the locked commit. One already there is
#  left as it is: `update` may have moved it forward on purpose.
# ═══════════════════════════════════════════════════════════════

plugin_dir() {
  case $1 in
    tmux/*) echo "$HOME/.tmux/plugins/${1#tmux/}" ;;
    zsh/*)  echo "$HOME/.zsh/plugins/${1#zsh/}" ;;
  esac
}

plugins_plan() {
  PLUGINS_MISSING=""
  local name url commit
  while read -r name url commit; do
    [ -d "$(plugin_dir "$name")/.git" ] || PLUGINS_MISSING="$PLUGINS_MISSING ${name#*/}"
  done < <(grep -v '^#' "$REPO/install/plugins.lock")
}

plugins_show_plan() {
  if [ -n "$PLUGINS_MISSING" ]; then info "plugins:$PLUGINS_MISSING"; else ok "every plugin is there"; fi
}

plugins_install() {
  step "tmux and zsh plugins"
  local name url commit dir
  while read -r name url commit; do
    dir=$(plugin_dir "$name")
    if [ -d "$dir/.git" ]; then
      ok "${name#*/} $(git -C "$dir" log -1 --format='%h · %cs' 2>/dev/null)"
      continue
    fi
    # a folder there that is not a clone (copied by hand, a clone cut short): git clone would
    # refuse it and stop the install · it is moved aside, never deleted
    if [ -d "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
      local old
      old="$dir.old-$(date +%Y%m%d-%H%M%S)"
      run mv "$dir" "$old"
      warn "${name#*/}: $(tilde "$dir") was not a git clone: moved to $(tilde "$old")"
    fi
    run mkdir -p "$(dirname "$dir")"
    run git clone -q "$url" "$dir"
    # the default branch moves back to the locked commit and keeps following the remote,
    # so `git pull` (update, tpm) can still move it forward later
    run git -C "$dir" reset -q --hard "$commit"
    ok "${name#*/} ${commit:0:7}"
  done < <(grep -v '^#' "$REPO/install/plugins.lock")
}
