#!/usr/bin/env bash
# shellcheck disable=SC2088  # "~/…" in messages is text to show, not a path
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · check that everything is in place (run by install.sh, or alone:
#  bash install/doctor.sh). ✔ fine · ✘ needed and missing / too old · – optional
# ═══════════════════════════════════════════════════════════════

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
. "$REPO/install/lib.sh"
. "$REPO/install/versions.sh"
detect_platform
problems=0

# need <command> [minimum version] [command that prints the version]
need() {
  local cmd=$1 min=${2:-} ver
  if ! have "$cmd"; then
    fail "$cmd is missing"; problems=$((problems + 1)); return
  fi
  ver=$(eval "${3:-$cmd --version}" 2>/dev/null | grep -Eo '[0-9]+(\.[0-9]+)+[a-z]?' | head -1)
  if [ -n "$min" ] && ! version_ge "${ver:-0}" "$min"; then
    fail "$cmd ${ver:-?} is too old (needs ≥ $min)"; problems=$((problems + 1))
  else
    ok "$cmd ${ver}"
  fi
}
optional() {
  if have "$1" || { [ "$1" = brew ] && [ -n "$(ls /opt/homebrew/bin/brew /usr/local/bin/brew \
       /home/linuxbrew/.linuxbrew/bin/brew 2>/dev/null)" ]; }; then ok "$1 ${D}(optional: $2)${R}"; else info "${D}– $1 not installed (optional: $2)${R}"; fi
}

printf '\n  %sTools%s\n' "$B" "$R"
need zsh
need tmux "$TMUX_MIN" "tmux -V"
need git
need python3 "$PYTHON_MIN"
need fzf "$FZF_MIN"
need starship
need eza
need bat
need micro
need btop
need fastfetch
need jq
need entr "" "entr -h 2>&1 | head -1; echo 0"
need ansifilter
need delta
need rg
need fd
need zoxide
need lazygit "" "lazygit --version | sed 's/.*version=//'"
need tldr
need shellcheck
if have yq && ! yq --version 2>&1 | grep -q mikefarah; then
  fail "yq is $(command -v yq), not mikefarah/yq (run ./install.sh)"; problems=$((problems + 1))
else need yq; fi
optional docker "the docker tab, Docker in the disk tab's Cleanup"
optional ssh "the ssh tab"
optional tig "tig from the git tab (lazygit is the default)"
optional gh "GitHub from the shell"
[ "$OS" = macos ] || optional snap "snap packages in the packages tab"
optional brew "Homebrew packages in the packages tab"
if [ "$OS" = macos ]; then
  need flock "" "echo 0"
  if infocmp tmux-256color >/dev/null 2>&1; then ok "tmux-256color terminal description"
  else fail "tmux-256color is unknown to macOS (run ./install.sh)"; problems=$((problems + 1)); fi
fi

printf '\n  %sConfig%s\n' "$B" "$R"
. "$REPO/install/config.sh"
for f in .zshrc .tmux.conf .zshenv; do
  case $f in .zshrc) want=$(block_zsh) ;; .zshenv) want=$(block_zshenv) ;; *) want=$(block_tmux) ;; esac
  case $f in .zshenv) what="skips the system's compinit (zsh/zshrc runs it)" ;; *) what="loads terminal-setup" ;; esac
  if has_block "$HOME/$f" && [ "$(block_in "$HOME/$f")" = "$want" ]; then ok "~/$f $what"
  elif [ $f = .zshenv ]; then fail "~/$f does not skip the system's compinit (run ./install.sh)"; problems=$((problems + 1))
  elif has_block "$HOME/$f"; then fail "~/$f loads terminal-setup from another folder (run ./install.sh)"; problems=$((problems + 1))
  else fail "~/$f does not load terminal-setup (run ./install.sh)"; problems=$((problems + 1)); fi
done
for f in $(links_into_repo); do
  fail "~/$f is still a link into the repo, from an older install (run ./install.sh)"; problems=$((problems + 1))
done

printf '\n  %sPlugins%s\n' "$B" "$R"
while read -r name _; do
  case $name in tmux/*) dir=$HOME/.tmux/plugins/${name#tmux/} ;; zsh/*) dir=$HOME/.zsh/plugins/${name#zsh/} ;; esac
  if [ -d "$dir/.git" ]; then ok "${name#*/}"; else fail "${name#*/} is missing (run ./install.sh)"; problems=$((problems + 1)); fi
done < <(grep -v '^#' "$REPO/install/plugins.lock")

printf '\n  %sFont%s\n' "$B" "$R"
. "$REPO/install/fonts.sh"
font_plan
case $FONT_TODO in
  none)    ok "JetBrainsMono Nerd Font is installed" ;;
  remote)  info "${D}– no desktop here: the font belongs on the computer you connect from${R}" ;;
  windows) fail "JetBrainsMono Nerd Font is not installed in Windows (see windows/windows-terminal.md)"; problems=$((problems + 1)) ;;
  linux)   fail "JetBrainsMono Nerd Font is not installed (run ./install.sh)"; problems=$((problems + 1)) ;;
  macos)   fail "JetBrainsMono Nerd Font is not installed (run ./install.sh: the Brewfile has it)"; problems=$((problems + 1)) ;;
esac
info "${D}icons look right only if your terminal uses it: \"JetBrainsMono Nerd Font\"${R}"

printf '\n'
if [ "$problems" = 0 ]; then
  printf '  %s✔ all good%s\n' "$GREEN$B" "$R"
else
  printf '  %s✘ %s problem(s) above%s\n' "$RED$B" "$problems" "$R"
  exit 1
fi
