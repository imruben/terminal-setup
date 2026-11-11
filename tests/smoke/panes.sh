#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Every monitor pane started on its own in a private tmux server (your tmux is not touched),
#  given keys (move, sort, tabs, filter) and a resize, then checked: still running, nothing on
#  stderr, no Python traceback on screen.      tests/smoke/panes.sh [seconds per pane, 3]
#  Uses what this machine has: with no Docker or no git repos the panes say so, which is fine.
# ═══════════════════════════════════════════════════════════════
set -u
R=$(cd "$(dirname "$0")/../.." && pwd)
WAIT=${1:-3}
SOCK="ts-smoke-$$"
OUT=$(mktemp -d)
T() { tmux -L "$SOCK" -f /dev/null "$@"; }
trap 'T kill-server 2>/dev/null; rm -rf "$OUT"' EXIT

PANES="procs ports disk_folders disk_mounts disk_cleanup packages pkgsearch updates pkginfo
       ssh_hosts ssh_host ssh_keys docker docker_details docker_logs git_repos git_repo"

T new-session -d -s smoke -x 160 -y 45 "sleep 3600" || { echo "FAIL tmux did not start"; exit 1; }
# a client in a pseudo-terminal, as a terminal tab would be: with none, every pane counts as out of sight
attach="stty cols 160 rows 45; tmux -L '$SOCK' attach -t smoke"
if [[ $(uname) == Darwin ]]; then                # BSD script: file first, then the command
  ( TERM=xterm-256color script -q /dev/null sh -c "$attach" >/dev/null 2>&1 & )
else
  ( TERM=xterm-256color script -qfc "$attach" /dev/null >/dev/null 2>&1 & )
fi
for _ in $(seq 1 20); do [ -n "$(T list-clients 2>/dev/null)" ] && break; sleep 0.2; done
[ -n "$(T list-clients 2>/dev/null)" ] || { echo "FAIL no tmux client (is script(1) there?)"; exit 1; }
for p in $PANES; do
  T new-window -d -t smoke: -n "$p" "python3 -I '$R/tmux/$p.py' 2>'$OUT/$p.err'; echo EXITED \$?; sleep 3600"
done
sleep 2
# one at a time in sight (panes out of sight do not load) · the window is resized meanwhile
fails=0
for p in $PANES; do
  T select-window -t "smoke:$p"; sleep "$WAIT"
  for k in Down Down Up End Home Right Left Tab BTab; do T send-keys -t "smoke:$p" "$k"; sleep 0.05; done
  T send-keys -t "smoke:$p" -l "zz"; sleep 0.3; T send-keys -t "smoke:$p" BSpace BSpace
  T split-window -d -t "smoke:$p" -h -l 40% "sleep 3600"; sleep 0.7; T kill-pane -t "smoke:$p.1"; sleep 1     # narrower, then back
  screen=$(T capture-pane -p -t "smoke:$p")
  why=""
  grep -q "^EXITED" <<<"$screen" && why="it ended ($(grep "^EXITED" <<<"$screen"))"
  grep -q "Traceback" <<<"$screen" && why="a traceback on screen"
  [ -s "$OUT/$p.err" ] && why="${why:+$why · }stderr: $(tail -3 "$OUT/$p.err" | tr '\n' ' ')"
  if [ -n "$why" ]; then
    echo "FAIL $p: $why"; fails=$((fails + 1))
  else
    printf 'PASS %-15s %s\n' "$p" "$(grep -v '^\s*$' <<<"$screen" | head -1 | cut -c1-70 | sed 's/  */ /g')"
  fi
done
# and after all that, still none ended or complained
for p in $PANES; do
  if T capture-pane -p -t "smoke:$p" | grep -q "^EXITED\|Traceback" || [ -s "$OUT/$p.err" ]; then
    echo "FAIL $p: failed later: $(tail -2 "$OUT/$p.err" | tr '\n' ' ')"; fails=$((fails + 1))
  fi
done
[ "$fails" = 0 ] && echo "✔ every pane runs" || echo "✘ $fails pane(s) failed"
exit $(( fails > 0 ))
