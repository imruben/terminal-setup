#!/usr/bin/env bash
# btop for the Info tab, with the boxes that fit this pane (btop refuses to draw
# when a box does not fit: "Terminal size too small"). Presets come from the repo's
# config/btop/btop.conf:  1 cpu mem net · 2 cpu mem · 3 cpu · 4 mem net. Your own
# btop keeps ~/.config/btop/btop.conf (a btop without -c reads that one: install.sh
# puts the repo's there when you have none).
# info-fit.sh restarts it when the pane changes enough to need other boxes.
# Out of sight it is stopped (see the end): btop costs the most of the monitor.
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
args=(-p "$p")
btop --help 2>&1 | grep -q -- '--config' && args=(-c "$conf" "${args[@]}")

# Out of sight (another tab, another session, nobody attached, another pane zoomed) btop is
# stopped (SIGSTOP): it is the panel that costs the most, every 2 s. Back in sight it goes on
# (SIGCONT, and btop redraws): tmux wakes this script with SIGUSR1 (@wake, tmux.conf hooks),
# else it looks again every 5 s. btop runs as its child: <&0 keeps the keyboard for it (a
# background job of a script would get /dev/null), and when it ends (q) the script ends too.
btop "${args[@]}" <&0 &
pid=$!
stopped=0
cleanup() {
  kill -CONT "$pid" 2>/dev/null                       # never leave it stopped
  [[ -n $TMUX_PANE ]] && tmux set -pu -t "$TMUX_PANE" @wake 2>/dev/null
}
trap cleanup EXIT
trap 'kill "$pid" 2>/dev/null; exit 0' HUP TERM INT
trap ':' USR1 CHLD WINCH                               # each one ends the wait below at once
[[ -n $TMUX_PANE ]] && tmux set -p -t "$TMUX_PANE" @wake $$
VIEW='#{&&:#{&&:#{window_active},#{session_attached}},#{||:#{?window_zoomed_flag,0,1},#{pane_active}}}'
while kill -0 "$pid" 2>/dev/null; do
  visible=1
  [[ -n $TMUX_PANE ]] && visible=$(tmux display -p -t "$TMUX_PANE" "$VIEW" 2>/dev/null)
  if [[ $visible == 0 && $stopped == 0 ]]; then kill -STOP "$pid" 2>/dev/null; stopped=1
  elif [[ $visible != 0 && $stopped == 1 ]]; then kill -CONT "$pid" 2>/dev/null; stopped=0
  fi
  sleep 5 & wait $!; kill $! 2>/dev/null
done
wait "$pid"
