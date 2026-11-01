#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · every file the install put on this machine, and what it is for
#    bash install/files.sh      (also: make files)
#  ✔ there · – not there (not needed here, or not created yet)
#  Packages are the ones the setup uses: the install only adds those that were missing,
#  so some may have been there before it.
# ═══════════════════════════════════════════════════════════════

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
. "$REPO/install/lib.sh"
. "$REPO/install/config.sh"
detect_platform
USER=${USER:-$(id -un)}

# file <path> <what it is for>
file() {
  if [ -e "$1" ] || [ -L "$1" ]; then
    printf '    %s✔%s %-44s %s\n' "$GREEN" "$R" "$(tilde "$1")" "$2"
  else
    printf '    %s– %-44s %s%s\n' "$D" "$(tilde "$1")" "$2" "$R"
  fi
}
group() { printf '\n  %s%s%s  %s%s%s\n' "$B" "$1" "$R" "$D" "$2" "$R"; }

group "Your files" "the install adds a few lines at their end, between two marks"
for f in .zshrc .tmux.conf; do
  if has_block "$HOME/$f"; then
    lines=$(grep -nF -e "$MARK_BEGIN" -e "$MARK_END" "$HOME/$f" | cut -d: -f1 | paste -sd- -)
    file "$HOME/$f" "loads the repo's $([ $f = .zshrc ] && echo zsh/zshrc || echo tmux/tmux.conf) · lines $lines"
  else
    printf '    %s– %-44s does not load terminal-setup (run ./install.sh)%s\n' "$D" "~/$f" "$R"
  fi
done

group "Loaded from the repo, not copied" "$(tilde "$REPO") · edit them there: git pull brings the changes to every machine"
case $OS:$IS_WSL in macos:*) plat=macos ;; *:1) plat=wsl ;; *) plat=linux ;; esac
repofile() { [ -e "$REPO/$1" ] && printf '    %s✔%s %-44s %s\n' "$GREEN" "$R" "$1" "$2"; }
repofile zsh/zshrc "zsh: history, keys, completion, plugins, tmux autostart (your ~/.zshrc sources it)"
repofile zsh/aliases.zsh "aliases (loaded by zsh/zshrc)"
repofile zsh/functions.zsh "functions: update, clean, ports, killport, dps, dsh, fkill, vps, installed-packages, terminal"
repofile "zsh/platform/$plat.zsh" "what only $plat needs: open, clipboard, ssh-agent…"
repofile config/starship.toml "the prompt (STARSHIP_CONFIG points here)"
repofile tmux/tmux.conf "tmux: keys, mouse, bar, menus (your ~/.tmux.conf sources it)"
repofile tmux/ "the system monitor, session picker, guide, quick menu"

group "Settings copied from the repo" "only when you had none · yours from then on"
while read -r src dst; do
  [ -n "$src" ] || continue
  case $dst in
    *btop*)  why="btop: the theme and the layouts of the monitor's btop pane" ;;
    *micro*) why="micro: the editor's settings" ;;
    *)       why="" ;;
  esac
  if [ -e "$HOME/$dst" ] && ! cmp -s "$REPO/$src" "$HOME/$dst"; then why="$why (yours: differs from the repo's)"; fi
  file "$HOME/$dst" "$why"
done <<< "$COPIES"

group "Plugins" "git clones at the versions in install/plugins.lock · update moves them forward"
plugin_why() {
  case $1 in
    tpm)              echo "tmux plugin manager: loads the others" ;;
    tmux-resurrect)   echo "saves and restores the sessions" ;;
    tmux-continuum)   echo "saves the sessions every 5 min, restores them when tmux starts" ;;
    extrakto)         echo "Ctrl+a e: pick any word, path or line on screen" ;;
    tmux-fzf-url)     echo "Ctrl+a u: open a link from the screen" ;;
    tmux-logging)     echo "Ctrl+a P: log a pane to ~/.tmux/logs" ;;
    tmux-cowboy)      echo "Ctrl+a *: kill a stuck program" ;;
    tmux-autoreload)  echo "reloads tmux when its config is saved" ;;
    fzf-tab)          echo "zsh: completion menu with fzf and previews" ;;
    *)                echo "" ;;
  esac
}
while read -r name url commit; do
  case $name in
    tmux/*) dir=$HOME/.tmux/plugins/${name#tmux/} ;;
    zsh/*)  dir=$HOME/.zsh/plugins/${name#zsh/} ;;
    *)      continue ;;
  esac
  file "$dir" "$(plugin_why "${name#*/}")"
done < <(grep -v '^#' "$REPO/install/plugins.lock")

group "Programs outside the package manager" "when the system's own version is missing or too old"
file /usr/local/bin/tmux "tmux built from source (Ubuntu 24.04: its tmux is older than 3.6)"
file "$HOME/.local/bin/fzf" "fzf official binary (when Ubuntu's is older than 0.48)"
file "$HOME/.local/bin/starship" "the prompt, official installer (when Ubuntu has no starship)"
file "$HOME/.local/bin/bat" "a link to batcat: Ubuntu calls bat \"batcat\""
if [ "$OS" = macos ]; then
  file "$HOME/.terminfo" "tmux-256color terminal description (macOS lacks it)"
elif [ "$IS_WSL" = 1 ]; then
  printf '    %s– the font goes in Windows (winget install --id DEVCOM.JetBrainsMonoNerdFont)%s\n' "$D" "$R"
else
  file "$HOME/.local/share/fonts/JetBrainsMonoNerdFont" "the Nerd Font: icons of the prompt, the bar and the panels"
fi

group "Packages" "what each one is for · the install adds only the missing ones"
pkg_why() {
  case $1 in
    zsh) echo "the shell" ;;                     git) echo "version control · the plugins are git clones" ;;
    curl|ca-certificates) echo "downloads during the install" ;;
    python3) echo "the system monitor panes, the guide, the session picker" ;;
    jq) echo "JSON on the command line" ;;      eza) echo "ls with icons and colours" ;;
    bat) echo "cat with colours · previews" ;;   micro) echo "the editor (EDITOR)" ;;
    btop) echo "the btop pane of the monitor" ;; entr) echo "tmux-autoreload watches the config with it" ;;
    ansifilter) echo "clean logs (tmux-logging)" ;; git-delta) echo "git diffs side by side, coloured" ;;
    zsh-autosuggestions) echo "zsh: grey suggestions from your history" ;;
    zsh-syntax-highlighting) echo "zsh: colours the command as you type" ;;
    fontconfig|unzip) echo "installing the font" ;;
    iproute2|lsof) echo "the Ports pane (ss / lsof)" ;; psmisc) echo "killport (fuser)" ;;
    procps) echo "ps, free, top" ;;              wl-clipboard) echo "pbcopy / pbpaste" ;;
    tmux) echo "the terminal multiplexer" ;;     fzf) echo "fuzzy finder: Ctrl+r, Ctrl+t, pickers" ;;
    fastfetch) echo "the Info pane of the monitor" ;; starship) echo "the prompt" ;;
    ncurses) echo "tmux-256color description" ;; coreutils) echo "gdircolors, gnumfmt" ;;
    flock) echo "the system monitor's lock" ;;   bash) echo "bash ≥ 4.2 for tmux-autoreload" ;;
    font-jetbrains-mono-nerd-font) echo "the Nerd Font" ;;
    *) echo "" ;;
  esac
}
if [ "$OS" = macos ]; then
  installed=$(brew list -1 2>/dev/null)
  for p in $(awk -F'"' '/^(brew|cask) /{print $2}' "$REPO/install/Brewfile"); do
    if printf '%s\n' "$installed" | grep -qx "$p"; then mark="$GREEN✔$R"; else mark="$D–$R"; fi
    printf '    %s %-30s %s\n' "$mark" "brew $p" "$(pkg_why "$p")"
  done
else
  . "$REPO/install/apt.sh"
  for p in $APT_PACKAGES $APT_DESKTOP tmux fzf fastfetch starship; do
    v=$(dpkg-query -W -f='${Status}\t${Version}' "$p" 2>/dev/null | awk -F'\t' '$1 ~ / installed$/ {print $2}')
    bin=$p; [ "$p" = git-delta ] && bin=delta
    if [ -n "$v" ]; then
      printf '    %s✔%s %-30s %s %s(%s)%s\n' "$GREEN" "$R" "apt $p" "$(pkg_why "$p")" "$D" "$v" "$R"
    elif have "$bin"; then                    # not from apt: say where it is
      printf '    %s✔%s %-30s %s %s(%s)%s\n' "$GREEN" "$R" "$p" "$(pkg_why "$p")" "$D" "$(tilde "$(command -v "$bin")")" "$R"
    else
      printf '    %s– %-30s %s%s\n' "$D" "apt $p" "$(pkg_why "$p")" "$R"
    fi
  done
fi

group "What it keeps while you use it" "your data: uninstall leaves it"
file "$HOME/.tmux/logs" "pane logs, saved histories, saved container logs"
file "$HOME/.tmux/descriptions.tsv" "what each session is for (session picker → Describe)"
file "${XDG_DATA_HOME:-$HOME/.local/share}/tmux/resurrect" "the saved sessions (tmux-resurrect)"
file "$HOME/.apt-notes.tsv" "why you installed each package (Packages pane → Why…)"
file "$HOME/.apt-base.txt" "apt packages the system came with (not shown as yours)"

group "Backups" "your files as they were before a change, just in case · nothing deletes them"
backups=$(ls -1d "$HOME"/.terminal-setup-backup/*/ 2>/dev/null)
if [ -z "$backups" ]; then
  printf '    %s– none yet: an install only makes one when it changes a file of yours%s\n' "$D" "$R"
fi
for b in $backups; do
  b=${b%/}
  d=${b##*/}                                   # 20261030-170937[-note]
  when="${d:0:4}-${d:4:2}-${d:6:2} ${d:9:2}:${d:11:2}"
  note=${d:16}                                 # e.g. "pre-repo"
  printf '    %s✔%s %-44s %s%s · %s\n' "$GREEN" "$R" "$(tilde "$b")" "$when" "${note:+ · $note}" \
    "$(du -sh "$b" 2>/dev/null | cut -f1)"
  for f in "$b"/.[!.]* "$b"/*; do
    [ -e "$f" ] || continue
    if [ -d "$f" ]; then
      printf '        %-42s %scopy of ~/%s/ · %s files%s\n' "${f##*/}/" "$D" "${f#"$b"/}" "$(find "$f" -type f | wc -l | tr -d ' ')" "$R"
    else
      printf '        %-42s %scopy of ~/%s%s\n' "${f##*/}" "$D" "${f#"$b"/}" "$R"
    fi
  done
done

group "Login shell" ""
shell=$( [ "$OS" = macos ] && dscl . -read "/Users/$USER" UserShell 2>/dev/null | awk '{print $2}' \
         || getent passwd "$USER" | cut -d: -f7 )
case $shell in */zsh) ok "zsh ($shell)" ;; *) info "${shell:-unknown} (the install offers to change it to zsh)" ;; esac
printf '\n'

