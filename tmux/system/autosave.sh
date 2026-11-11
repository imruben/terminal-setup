#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Saves the sessions (tmux-resurrect) every @autosave-interval minutes, in place of
#  tmux-continuum's own saving. Continuum only saves when it believes it is the one tmux
#  server, and it counts every process whose name starts with "tmux": the monitor's panes ask
#  tmux things all the time, so it nearly always decided another server was running and never
#  saved. Its status-line hook also ran ~20 processes every few seconds per client.
#  This waits asleep between saves: nothing runs in between.
#  Run from tmux.conf (run-shell -b): one per server, its pid in @autosave-pid · a config
#  reload starts another, which leaves if the first is still there · it ends with the server.
# ═══════════════════════════════════════════════════════════════
save=~/.tmux/plugins/tmux-resurrect/scripts/save.sh
me=$$

old=$(tmux show -gqv @autosave-pid 2>/dev/null)
if [[ -n $old && $old != "$me" ]] && kill -0 "$old" 2>/dev/null \
   && ps -o args= -p "$old" 2>/dev/null | grep -q autosave.sh; then
  exit 0                                       # this server has one already
fi
tmux set -g @autosave-pid "$me"

while :; do
  minutes=$(tmux show -gqv @autosave-interval 2>/dev/null) || exit 0     # the server is gone
  [[ $minutes =~ ^[0-9]+$ ]] || minutes=5
  (( minutes > 0 )) || exit 0                  # 0: no saving
  sleep $(( minutes * 60 )) & wait $!
  # still this server's, and it still runs (a kill-server ends the loop here)
  [[ $(tmux show -gqv @autosave-pid 2>/dev/null) == "$me" ]] || exit 0
  [[ -x $save ]] && "$save" quiet
done
