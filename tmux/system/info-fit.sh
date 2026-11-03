#!/usr/bin/env bash
# window-resized hook of the Info tab (and run once when it is built):
#  · Resources keeps its height
#  · the width is shared so btop always shows the CPU and fastfetch keeps its drawing:
#      ≥ 191 cols  fastfetch 110 (big drawing)  · btop the rest (all boxes from 80)
#      141–190     btop ≥ 60 (CPU + memory, 70 adds network) · fastfetch the rest (small drawing)
#      narrower    about half each, but btop never under its 50-col minimum while
#                  fastfetch keeps 25 (at 80 cols: fastfetch 29 · btop 50)
#  · btop is restarted only when the boxes that fit change (btop.sh picks them)
# info-fit.sh <resources pane> <btop pane> <rows for resources>
res=$1 btop=$2 rows=$3
# zoomed: resizing a pane would undo the zoom (tmux unzooms on resize-pane): the next resize fits it
[[ $(tmux display -p -t "$1" '#{window_zoomed_flag}' 2>/dev/null) == 1 ]] && exit 0
W=$(tmux display -p -t "$btop" '#{window_width}' 2>/dev/null) || exit 0
if   (( W >= 191 )); then bw=$(( W - 111 ))
elif (( W >= 141 )); then bw=$(( W - 81 )); (( bw > 70 )) && bw=70; (( bw < 60 )) && bw=60
else                      bw=$(( W / 2 )); (( bw < 50 && W - 51 >= 25 )) && bw=50
fi
tmux resize-pane -t "$btop" -x "$bw" 2>/dev/null
tmux resize-pane -t "$res" -y "$rows" 2>/dev/null
size=$(tmux display -p -t "$btop" '#{pane_width} #{pane_height}')
want=$("$(dirname "$0")/btop.sh" --preset-for $size)
have=$(tmux show -pqv -t "$btop" @btop-preset)
[[ -n $have && $want != "$have" ]] && tmux respawn-pane -k -t "$btop" "$(dirname "$0")/keep.sh $(dirname "$0")/btop.sh"
exit 0
