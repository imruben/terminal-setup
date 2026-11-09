#!/usr/bin/env bash
# Old name of top-fit.sh: a system session built before the rename still runs it on resize
# (until tmux/system.sh rebuilds the session).
exec "$(dirname "$0")/top-fit.sh" "$1" 38
