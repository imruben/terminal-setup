#!/usr/bin/env bash
# window-layout-changed hook of the system session: when a tab has just left zoom, its panes
# get the heights its fit script gives them (info-fit, top-fit, disk-fit: the tab's @fit-cmd).
# tmux sends no window-resized on unzoom, and a terminal resized while zoomed would otherwise
# keep tmux's own scaled layout · any other layout change (a border dragged) is left alone.
# after-zoom.sh <window id>
w=$1
[[ -n $w ]] || exit 0
read -r zoomed last cmd < <(tmux display -p -t "$w" '#{window_zoomed_flag} #{?#{@zoom-last},#{@zoom-last},0} #{@fit-cmd}' 2>/dev/null) || exit 0
[[ $zoomed == [01] ]] || exit 0                     # no answer (the window just closed)
[[ $zoomed == "$last" ]] && exit 0
tmux set -w -t "$w" @zoom-last "$zoomed"
[[ $last == 1 && $zoomed == 0 && -n $cmd ]] && eval "$cmd"
exit 0
