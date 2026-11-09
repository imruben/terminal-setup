#!/usr/bin/env bash
# Runs a pane of the `system` session and, if it is closed (q in btop, Ctrl+c…),
# offers to start it again instead of leaving a hole in the layout.
while :; do
  "$@"
  # a program killed (kill -9, out of memory) leaves the terminal raw, mouse tracking on and
  # on the alternate screen: Enter would not end the read below
  stty sane 2>/dev/null
  printf '\e[?1003l\e[?1006l\e[?2004l\e[?7h\e[?25h\e[?1049l\e[0m'
  # its pid, noted for tmux to wake it (tmuxlink.note_wake), must not reach another process
  [[ -n $TMUX_PANE ]] && tmux set -pu -t "$TMUX_PANE" @wake 2>/dev/null
  name=${*: -1}; name=${name##*/}         # the program: python3 -I …/procs.py → procs.py
  printf '\n\e[38;2;108;112;134m  %s closed · Enter starts it again\e[0m' "$name"
  read -rs
  clear
done
