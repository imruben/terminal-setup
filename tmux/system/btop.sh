#!/usr/bin/env bash
# btop for the Info tab, with the boxes that fit this pane (btop refuses to draw
# when a box does not fit: "Terminal size too small"). Presets come from the repo's
# config/btop/btop.conf:  1 cpu mem net · 2 cpu mem · 3 cpu · 4 mem net. Your own
# btop keeps ~/.config/btop/btop.conf (a btop without -c reads that one: install.sh
# puts the repo's there when you have none).
# info-fit.sh restarts it when the pane changes enough to need other boxes.
preset_for() {
  local w=$1 h=$2
  if   (( w >= 80 && h >= 24 )); then echo 0     # + processes
  elif (( w >= 70 && h >= 24 )); then echo 1
  elif (( (w >= 60 && h >= 20) || (w >= 70 && h >= 18) )); then echo 2
  elif (( w >= 50 && h >= 16 )); then echo 4
  else echo none
  fi
}
[[ $1 == --preset-for ]] && { preset_for "$2" "$3"; exit; }

p=$(preset_for "$(tput cols)" "$(tput lines)")
tmux set -p -t "$TMUX_PANE" @btop-preset "$p"
if [[ $p == none ]]; then
  printf '\n  \e[38;2;108;112;134mbtop needs at least 50×16 · this pane is %s×%s\e[0m\n' "$(tput cols)" "$(tput lines)"
  trap 'exec "$0"' WINCH          # bigger now (zoomed, a larger window)? check again: btop when it fits
  while :; do sleep 60 & wait $!; done
fi
conf=$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)/config/btop/btop.conf
if btop --help 2>&1 | grep -q -- '--config'; then exec btop -c "$conf" -p "$p"; fi
exec btop -p "$p"
