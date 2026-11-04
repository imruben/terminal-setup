#!/usr/bin/env bash
# window-resized hook of the tabs with a list on top and details below (docker, ssh, git),
# also run once when they are built: the list keeps PERCENT of the height, never under MIN
# rows (title, column titles, a few rows and the detail line), while the panes below keep 9.
# tmux alone takes the rows a smaller window loses from the top pane first, which left
# the list with 2 rows in a small terminal.
# top-fit.sh <top pane> [percent (38)] [min rows (8)]
top=$1 pct=${2:-38} min=${3:-8}
read -r zoomed H < <(tmux display -p -t "$top" '#{window_zoomed_flag} #{window_height}' 2>/dev/null)
[[ $H =~ ^[0-9]+$ ]] || exit 0                 # the pane is gone
# zoomed: resizing a pane would undo the zoom (tmux unzooms on resize-pane): the next resize fits it
[[ $zoomed == 1 ]] && exit 0
want=$(( H * pct / 100 ))
(( want < min )) && want=$min
(( want > H - 9 )) && want=$(( H - 9 ))
(( want >= 3 )) && tmux resize-pane -t "$top" -y "$want" 2>/dev/null
exit 0
