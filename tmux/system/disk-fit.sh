#!/usr/bin/env bash
# The Disks pane of the disk tab keeps the height of its list: title, column titles,
# one row per disk (its @rows, set by tmux/disk_mounts.py) and the detail line, so
# Cleanup below gets the rest. Run by the pane when its number of disks changes and
# by the tab's window-resized hook. Never more than half the tab.
# disk-fit.sh <disks pane>
pane=$1
# zoomed: resizing a pane would undo the zoom (tmux unzooms on resize-pane): the next resize fits it
[[ $(tmux display -p -t "$1" '#{window_zoomed_flag}' 2>/dev/null) == 1 ]] && exit 0
rows=$(tmux display -p -t "$pane" '#{@rows}' 2>/dev/null) || exit 0
H=$(tmux display -p -t "$pane" '#{window_height}' 2>/dev/null) || exit 0
[[ $rows =~ ^[0-9]+$ ]] || rows=3
want=$(( rows + 3 ))
(( want > H / 2 )) && want=$(( H / 2 ))
(( want < 5 )) && want=5
tmux resize-pane -t "$pane" -y "$want" 2>/dev/null
exit 0
