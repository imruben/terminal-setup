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

# Plugins always use LF line endings. With core.autocrlf=true (common on Windows / WSL) git
# would write them with CRLF and zsh / tmux could not run them ("fzf-tab.zsh\r": no such file).
# A plugin checked out like that is written again, at the same commit.
plugin_lf() {
  local dir=$1 was
  was=$(git -C "$dir" config --get core.autocrlf)
  [ "$was" = false ] && return 0
  run git -C "$dir" config core.autocrlf false
  [ "$was" = true ] || [ "$was" = input ] || return 0      # nothing was converted
  run rm -f "$dir/.git/index"
  run git -C "$dir" reset -q --hard HEAD
  ok "${dir##*/}: line endings fixed (LF)"
}

plugins_install() {
  step "tmux and zsh plugins"
  local name url commit dir
  while read -r name url commit; do
    dir=$(plugin_dir "$name")
    if [ -d "$dir/.git" ]; then
      plugin_lf "$dir"
      ok "${name#*/} $(git -C "$dir" log -1 --format='%h · %cs' 2>/dev/null)"
      continue
    fi
    run mkdir -p "$(dirname "$dir")"
    run git clone -q -c core.autocrlf=false "$url" "$dir"
    # the default branch moves back to the locked commit and keeps following the remote,
    # so `git pull` (update, tpm) can still move it forward later
    run git -C "$dir" reset -q --hard "$commit"
    ok "${name#*/} ${commit:0:7}"
  done < <(grep -v '^#' "$REPO/install/plugins.lock")
}
