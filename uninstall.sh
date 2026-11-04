#!/usr/bin/env bash
# shellcheck disable=SC2088  # "~/…" in messages is text to show, not a path
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · undo the install
#    ./uninstall.sh         takes the terminal-setup lines out of ~/.zshrc, ~/.tmux.conf and ~/.zshenv
#                           (the rest of those files stays as it is)
#    ./uninstall.sh --yes   no questions
#  Packages, the font and the plugins stay installed (other things may use them), and
#  ~/.tmux too (your logs and session descriptions are there). The btop and micro
#  settings the install copied go, if you did not change them.
#  An install from before (links into the repo) is undone too: the links go and the
#  files from before it come back from ~/.terminal-setup-backup/.
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO=$(CDPATH='' cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
. "$REPO/install/lib.sh"
ASSUME_YES=0 DRY_RUN=0
case ${1:-} in -y|--yes) ASSUME_YES=1 ;; "") ;; *) die "unknown option: $1 (./uninstall.sh [--yes])" ;; esac
BACKUP_DIR="$HOME/.terminal-setup-backup/$(date +%Y%m%d-%H%M%S)"
. "$REPO/install/config.sh"

printf '\n%sterminal-setup · uninstall%s\n' "$B" "$R"
step "Plan"
blocks="" copies="" links=$(links_into_repo)
for f in .zshrc .tmux.conf .zshenv; do has_block "$HOME/$f" && { check_marks "$HOME/$f"; blocks="$blocks $f"; }; done
while read -r src dst; do
  [ -n "$src" ] && [ ! -L "$HOME/$dst" ] && cmp -s "$REPO/$src" "$HOME/$dst" && copies="$copies $dst"
done <<< "$COPIES"
[ -n "$blocks" ] && info "take the terminal-setup lines out of:$(printf ' ~/%s' $blocks)"
[ -n "$copies" ] && info "remove the copied settings:$(printf ' ~/%s' $copies)"
[ -n "$links" ]  && info "remove the links into the repo: $(printf '~/%s ' $links)"
[ -z "$blocks$copies$links" ] && { ok "terminal-setup is not set up here: nothing to do"; exit 0; }
ask "Go ahead?" || { info "nothing changed"; exit 0; }

step "Uninstall"
for f in $blocks; do
  backup_copy "$HOME/$f"
  without_block "$HOME/$f" > "$HOME/$f.tmp"
  if [ -s "$HOME/$f.tmp" ]; then
    cat "$HOME/$f.tmp" > "$HOME/$f"; ok "~/$f: terminal-setup lines taken out"
  else
    rm "$HOME/$f"; ok "~/$f removed (it only had the terminal-setup lines)"
  fi
  rm -f "$HOME/$f.tmp"
done
for f in $copies; do rm "$HOME/$f"; ok "removed ~/$f"; done

# ─── an install from before: links into the repo, the old files in a backup ───
if [ -n "$links" ]; then
  for f in $links; do
    if [ "$f" = .tmux ]; then              # what tmux wrote there comes along
      rm "$HOME/.tmux"; mkdir -p "$HOME/.tmux"
      for item in plugins logs resurrect descriptions.tsv; do
        [ -e "$REPO/tmux/$item" ] && mv "$REPO/tmux/$item" "$HOME/.tmux/"
      done
    else
      rm "$HOME/$f"
    fi
    ok "removed the link ~/$f"
  done
  # the newest backup with a MANIFEST (the one the old install made): this run's own copies
  # above went to a newer folder, without one
  old=$(ls -d "$HOME"/.terminal-setup-backup/*/MANIFEST 2>/dev/null | sort | tail -1 || true); old=${old%/MANIFEST}
  if [ -n "$old" ] && [ -f "$old/MANIFEST" ]; then
    while read -r rel; do
      [ -e "$old/$rel" ] || [ -L "$old/$rel" ] || continue
      if [ "$rel" = .tmux ] && [ -d "$HOME/.tmux" ]; then
        cp -Rn "$old/.tmux/." "$HOME/.tmux/" && ok "put back ~/.tmux (with what tmux wrote since)"; continue
      fi
      if [ -e "$HOME/$rel" ] || [ -L "$HOME/$rel" ]; then
        warn "~/$rel exists now: left as is (the old one stays in $(tilde "$old"))"; continue
      fi
      mkdir -p "$(dirname "$HOME/$rel")"
      mv "$old/$rel" "$HOME/$rel"
      ok "put back ~/$rel"
    done < "$old/MANIFEST"
  fi
fi

# shellcheck disable=SC2033  # tmux's own info command, not our info()
tmux info >/dev/null 2>&1 && [ -f "$HOME/.tmux.conf" ] && tmux source-file "$HOME/.tmux.conf" >/dev/null 2>&1 || true
[ -d "$BACKUP_DIR" ] && printf '\n    A copy of your files as they were: %s\n' "$(tilde "$BACKUP_DIR")"
printf '\n    Done. Open a new terminal (a running tmux keeps the old key bindings until it restarts).\n\n'
