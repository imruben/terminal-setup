#!/bin/bash
# shellcheck disable=SC2088   # the ~ in the PASS / FAIL labels is text
# Runs inside a fresh Ubuntu container as the user "tester" (passwordless sudo), started by
# run.sh, which copied the repo to "$HOME/my repos/terminal-setup" (a space on purpose).
# Prints PASS/FAIL lines and what helps to read them; DONE at the end.
set -u
R="$HOME/my repos/terminal-setup"
pass() { echo "PASS $*"; }
failc() { echo "FAIL $*"; }
check() { local what=$1; shift; if "$@" >/dev/null 2>&1; then pass "$what"; else failc "$what"; fi; }
section() { echo; echo "===== $* ====="; }

section "install (first run)"
cd "$R" || exit 1
t0=$(date +%s)
./install.sh --yes > ~/install1.log 2>&1; rc=$?
echo "install rc=$rc in $(( $(date +%s) - t0 ))s"
tail -25 ~/install1.log
[ $rc = 0 ] && pass "install.sh --yes exits 0" || failc "install.sh --yes exits $rc"
grep -q "checksum is not" ~/install1.log && failc "a checksum did not match" || pass "no checksum mismatch"
check "repo link made (path has a space)" test -L "$HOME/.local/share/terminal-setup"
check "~/.zshrc loads the repo through the link" grep -q 'source "'"$HOME"'/.local/share/terminal-setup/zsh/zshrc"' ~/.zshrc
check "~/.tmux.conf has the link" grep -q "TERMINAL_SETUP=\"$HOME/.local/share/terminal-setup\"" ~/.tmux.conf
check "login shell is zsh" sh -c 'getent passwd tester | grep -q zsh$'

section "versions"
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
for c in tmux fzf starship lazygit yq fastfetch eza bat rg fd zoxide shellcheck btop delta micro; do
  printf '%-10s %s\n' "$c" "$(command -v $c >/dev/null 2>&1 && ($c --version 2>/dev/null || $c -V 2>/dev/null) | head -1 || echo MISSING)"
done
check "tmux >= 3.6" sh -c 'tmux -V | grep -Eq "3\.([6-9]|[1-9][0-9])"'
check "starship works" starship --version
check "yq is mikefarah's" sh -c 'yq --version | grep -q mikefarah'

section "zsh"
out=$(zsh -ic 'echo TS=$TERMINAL_SETUP; type update extract rgf fe terminal >/dev/null && echo FUNCS-OK' 2>&1 </dev/null)
echo "$out" | tail -5
echo "$out" | grep -q "TS=$HOME/.local/share/terminal-setup" && pass "zsh TERMINAL_SETUP is the link" || failc "zsh TERMINAL_SETUP: $(echo "$out" | grep TS=)"
echo "$out" | grep -q FUNCS-OK && pass "zsh functions load" || failc "zsh functions"
echo "$out" | grep -iqE "command not found|no such file|unknown option|parse error" && failc "zsh startup prints errors" || pass "zsh starts clean"
mkdir -p ~/ex/src ~/ex/here && echo hola > ~/ex/src/a.txt && gzip -k ~/ex/src/a.txt
(cd ~/ex/here && zsh -ic 'extract ~/ex/src/a.txt.gz' </dev/null >/dev/null 2>&1); check "extract unpacks here" test -f ~/ex/here/a.txt

section "make check / doctor / files"
(cd "$R" && make check) > ~/check.log 2>&1 && pass "make check" || { failc "make check"; tail -5 ~/check.log; }
(cd "$R" && make test) > ~/unit.log 2>&1 && pass "unit tests ($(grep -o 'Ran [0-9]* tests' ~/unit.log))" || { failc "unit tests"; tail -20 ~/unit.log; }
bash "$R/install/doctor.sh" > ~/doctor.log 2>&1; drc=$?
grep -E "✘|!" ~/doctor.log | head
[ $drc = 0 ] && pass "doctor: no problems" || failc "doctor rc=$drc"
bash "$R/install/files.sh" > ~/files.log 2>&1 && pass "files.sh runs" || failc "files.sh"
grep -q "a link to the repo, whose folder has spaces" ~/files.log && pass "files.sh lists the link" || failc "files.sh link line"

section "tmux + system monitor"
tmux kill-server 2>/dev/null
# a client in a pseudo-terminal, like a real terminal tab (tmux starts, ~/.tmux.conf builds `system`)
( TERM=xterm-256color script -qfc "stty cols 200 rows 50; tmux new -s work" /dev/null >/dev/null 2>&1 & )
for _ in $(seq 1 60); do tmux has -t =system 2>/dev/null && [ "$(tmux list-panes -s -t =system 2>/dev/null | wc -l)" -ge 20 ] && break; sleep 1; done
sleep 3
panes=$(tmux list-panes -s -t =system -F '#{@label}' 2>/dev/null | sort | tr '\n' ' ')
echo "labels: $panes"
[ "$(tmux list-panes -s -t =system 2>/dev/null | wc -l)" -ge 20 ] && pass "system monitor built ($(tmux list-panes -s -t =system | wc -l) panes)" || failc "system monitor not built"
cmds=$(tmux list-panes -s -t =system -F '#{pane_start_command}' | head -3)
echo "$cmds" | grep -q "share/terminal-setup" && pass "pane commands use the link" || failc "pane commands: $cmds"
check "config loaded without errors" sh -c '! tmux show-messages 2>/dev/null | grep -iE "error|unknown|invalid"'
tmux switch-client -c "$(tmux list-clients -F '#{client_name}' | head -1)" -t =system 2>/dev/null
for w in info monitor disk packages ssh docker git; do
  tmux select-window -t "system:$w"; sleep 6
  bad=$(tmux list-panes -t "system:$w" -F '#{pane_id} #{@label}' | while read -r p l; do
          tmux capture-pane -p -t "$p" | grep -qE "Traceback|Error:|closed · Enter starts" && echo "$l"; done)
  first=$(tmux list-panes -t "system:$w" -F '#{pane_id} #{@label}' | while read -r p l; do
            printf '%s: %s · ' "$l" "$(tmux capture-pane -p -t "$p" | grep -v '^\s*$' | head -1 | cut -c1-60 | sed 's/  */ /g')"; done)
  echo "[$w] $first"
  [ -z "$bad" ] && pass "tab $w: no errors" || { failc "tab $w: errors in $bad"; for p in $(tmux list-panes -t "system:$w" -F '#{pane_id}'); do tmux capture-pane -p -t "$p" | grep -B2 -A8 Traceback | head -20; done; }
done
# every pane on its own, given keys (a private tmux server)
bash "$R/tests/smoke/panes.sh" > ~/smoke.log 2>&1 && pass "smoke: every pane runs" || { failc "smoke"; grep FAIL ~/smoke.log; }
# sessions are saved by autosave.sh (one loop per server); continuum's own saving is off
ap=$(tmux show -gqv @autosave-pid)
[ -n "$ap" ] && ps -o args= -p "$ap" | grep -q autosave.sh && pass "autosave loop running (pid $ap)" || failc "autosave loop not running"
[ "$(tmux show -gqv @continuum-save-interval)" = 0 ] && pass "continuum's own saving off" || failc "continuum save interval: $(tmux show -gqv @continuum-save-interval)"
tmux source-file ~/.tmux.conf; sleep 2
[ "$(pgrep -fc 'tmux/system/autosave.sh')" -le 2 ] && pass "config reload: still one autosave loop" || failc "autosave loops after reload: $(pgrep -fc 'tmux/system/autosave.sh')"
# zsh startup time
t0=$(date +%s%N); for _ in 1 2 3 4 5; do TERMINAL_NO_AUTOSTART=1 zsh -i -c exit </dev/null >/dev/null 2>&1; done
echo "zsh interactive start: $(( ($(date +%s%N) - t0) / 5000000 )) ms"
# btop sleeps out of sight
tmux select-window -t system:git; sleep 7
bt=$(pgrep -x btop | head -1); st=$(ps -o stat= -p "$bt" 2>/dev/null | tr -d ' ')
[[ $st == T* ]] && pass "btop stopped out of sight ($st)" || failc "btop state out of sight: $st"
tmux select-window -t system:info; sleep 1
w=$(tmux list-panes -t system:info -F '#{@label} #{@wake}' | awk '$1=="btop"{print $2}'); [ -n "$w" ] && kill -USR1 "$w"; sleep 1
st=$(ps -o stat= -p "$bt" 2>/dev/null | tr -d ' '); [[ $st != T* ]] && pass "btop back in sight ($st)" || failc "btop still stopped: $st"
# a closed monitor pane comes back
tmux kill-pane -t "$(tmux list-panes -s -t =system -F '#{pane_id} #{@label}' | awk '$2=="Ports"{print $1}')"
for _ in $(seq 1 30); do [ "$(tmux list-panes -s -t =system -F '#{@label}' | grep -c '^Ports$')" = 1 ] && break; sleep 1; done
[ "$(tmux list-panes -s -t =system -F '#{@label}' | grep -c '^Ports$')" = 1 ] && pass "closed pane: monitor repaired" || failc "monitor not repaired"
# a closed session forgets its description
printf 'gone\told text\nkeep\tstays\n' > ~/.tmux/descriptions.tsv
tmux new -d -s gone; tmux kill-session -t gone; sleep 3
grep -q '^gone' ~/.tmux/descriptions.tsv && failc "description of a closed session stays" || pass "closed session forgets its description"
grep -q '^keep' ~/.tmux/descriptions.tsv && pass "other descriptions stay" || failc "other descriptions lost"
# Resources fits its rows
res=$(tmux list-panes -t system:info -F '#{pane_id} #{@label} #{pane_height} #{@rows}' | awk '$2=="Resources"')
echo "Resources: $res"; set -- $res; [ "$3" = "$4" ] && pass "Resources height = its rows ($3)" || failc "Resources height $3 vs rows $4"

section "install again (update mode, idempotent)"
cd "$R" && ./install.sh --yes > ~/install2.log 2>&1; rc=$?
grep -E "Update|update" ~/install2.log | head -3
[ $rc = 0 ] && pass "second install exits 0" || { failc "second install rc=$rc"; tail -15 ~/install2.log; }
[ "$(grep -c 'terminal-setup' ~/.zshrc)" -le 3 ] && pass "~/.zshrc block not duplicated" || failc "~/.zshrc duplicated"

section "uninstall"
tmux kill-server 2>/dev/null
cd "$R" && ./uninstall.sh --yes > ~/uninstall.log 2>&1; rc=$?
tail -8 ~/uninstall.log
[ $rc = 0 ] && pass "uninstall exits 0" || failc "uninstall rc=$rc"
check "link removed" test ! -e "$HOME/.local/share/terminal-setup"
check "~/.tmux.conf gone or without the block" sh -c '! grep -q terminal-setup ~/.tmux.conf 2>/dev/null'
echo DONE
