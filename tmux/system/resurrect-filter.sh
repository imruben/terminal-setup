#!/usr/bin/env bash
# tmux-resurrect post-save hook: drop the `system` session from the save file.
# resurrect could not restart btop & co, and tmux/system.sh rebuilds it anyway.
#
# A save with nothing left (only `system` was open: WSL shutting down, a client going away
# before the sessions were restored…) must not replace the last real save, or the next start
# would bring back nothing. It is made identical to the last save, so resurrect drops it.
# Its pane contents too: resurrect writes pane_contents.tar.gz after this hook, so the last good
# one is put aside here and back by the post-save-all hook (resurrect-filter.sh --contents).
# `terminal kill-all` really means "nothing": it saves with TERMINAL_SAVE_EMPTY=1.
if [[ $1 == --contents ]]; then                 # post-save-all: the kept contents go back
  for dir in "$(tmux show -gqv @resurrect-dir 2>/dev/null)" ~/.tmux/resurrect \
             "${XDG_DATA_HOME:-$HOME/.local/share}/tmux/resurrect"; do
    dir=${dir/#\~/$HOME}
    [[ -n $dir && -f $dir/pane_contents.tar.gz.keep ]] && mv -f "$dir/pane_contents.tar.gz.keep" "$dir/pane_contents.tar.gz"
  done
  exit 0
fi
file=$1
[[ -f $file ]] || exit 0
awk -F'\t' '!(($1 == "pane" || $1 == "window" || $1 == "grouped_session") && $2 == "system")' "$file" > "$file.tmp" \
  && mv "$file.tmp" "$file"
dir=$(dirname "$file")
rm -f "$dir/pane_contents.tar.gz.keep"          # one left by a save that died halfway: not this save's
last=$dir/last
if [[ -z $TERMINAL_SAVE_EMPTY ]] && ! grep -q '^pane' "$file" && grep -qs '^pane' "$last"; then
  cat "$last" > "$file"
  [[ -f $dir/pane_contents.tar.gz ]] && cp -f "$dir/pane_contents.tar.gz" "$dir/pane_contents.tar.gz.keep"
fi
exit 0
