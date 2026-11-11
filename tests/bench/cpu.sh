#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  CPU of the system monitor: every pane (its whole process tree) and the tmux server, while
#  the info, docker and git tabs are in sight and while the monitor is out of sight.
#      tests/bench/cpu.sh [seconds per scenario, 30] [repo, this one]
#  Runs a private tmux server (its own TMUX_TMPDIR: your tmux is not touched) with the repo's
#  tmux.conf minus the plugins. Linux (/proc). Compare two versions with a git worktree:
#      git worktree add /tmp/old HEAD~1 && tests/bench/cpu.sh 30 /tmp/old
# ═══════════════════════════════════════════════════════════════
SECS=${1:-30}
R=$(cd "${2:-$(dirname "$0")/../..}" && pwd)
export TMUX_TMPDIR; TMUX_TMPDIR=$(mktemp -d /tmp/tsb.XXXX)     # short: socket paths have a length limit
trap 'tmux kill-server 2>/dev/null; rm -rf "$TMUX_TMPDIR"' EXIT
unset TMUX
CONF="$TMUX_TMPDIR/perf.conf"
{ echo "TERMINAL_SETUP=\"$R\""; grep -v "^run.*tpm\|@plugin\|continuum\|resurrect\|autoreload\|autosave" "$R/tmux/tmux.conf"; } > "$CONF"
( TERM=xterm-256color script -qfc "stty cols 200 rows 50; tmux -f '$CONF' new -s work" /dev/null >/dev/null 2>&1 & )
for _ in $(seq 1 90); do [ "$(tmux list-panes -s -t =system 2>/dev/null | wc -l)" -ge 20 ] && break; sleep 1; done
if [ "$(tmux list-panes -s -t =system 2>/dev/null | wc -l)" -lt 20 ]; then echo "MONITOR DID NOT START"; tmux ls; exit 1; fi
sleep 8
HZ=$(getconf CLK_TCK)
tree_ticks() {   # utime+stime (+ reaped children) of a pane's process and its descendants
  local total=0 p f
  for p in $1 $(pgrep -P "$1") $(for c in $(pgrep -P "$1"); do pgrep -P "$c"; done); do
    f=$(sed 's/^.*) //' /proc/$p/stat 2>/dev/null) || continue
    set -- $f
    total=$(( total + ${12} + ${13} + ${14} + ${15} ))
  done
  echo $total
}
snapshot() { tmux list-panes -s -t =system -F '#{pane_pid} #{@label}' | while read -r pid label; do echo "$label $(tree_ticks "$pid")"; done | sort; }
server_ticks() { local f; f=$(sed 's/^.*) //' "/proc/$(tmux display -p '#{pid}')/stat"); set -- $f; echo $(( ${12} + ${13} + ${14} + ${15} )); }
scenario() {
  local a b s0 s1
  a=$(snapshot); s0=$(server_ticks); sleep "$SECS"; b=$(snapshot); s1=$(server_ticks)
  echo "== $1"
  join <(echo "$a") <(echo "$b") | awk -v hz="$HZ" -v secs="$SECS" -v srv="$((s1 - s0))" '
    { d = $3 - $2; tot += d; printf "  %-11s %5.2f%%\n", $1, d * 100 / hz / secs }
    END { printf "  %-11s %5.2f%%\n  %-11s %5.2f%%\n", "ALL PANES", tot * 100 / hz / secs, "tmux server", srv * 100 / hz / secs }'
}
client=$(tmux list-clients -F '#{client_name}' | head -1)
tmux switch-client -c "$client" -t =system; tmux select-window -t system:info; sleep 4
scenario "visible: info"
tmux select-window -t system:docker; sleep 4
scenario "visible: docker"
tmux select-window -t system:git; sleep 4
scenario "visible: git"
tmux switch-client -c "$client" -t =work; sleep 4
scenario "out of sight"
exit 0
