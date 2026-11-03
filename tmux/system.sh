#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  `system` session: a live system monitor that is always there
#
#    1 info:      fastfetch         │ btop
#                 Resources         │
#    2 monitor:   Processes │ Ports                      (interactive: hover, right-click,
#    3 disk:      Folders   │ Disks                       type to filter, click a title
#                           │ Cleanup                     to sort, Del asks to stop)
#    4 packages:  Packages  │ Search
#                 Updates   │ Package (details)
#    5 ssh:       Hosts
#                 Host (details · config · recent) │ Keys
#    6 docker:    Containers (like dps)
#                 Container (details · Dockerfile · Compose) │ Logs (live)
#    7 git:       Repos (the folders of ~/.tmux/git-roots)
#                 Repo (status · diff · log · branches · stash)
#
#  system.sh                 open it (attach, or switch when already in tmux)
#  system.sh go <client>     switch that client to it (Ctrl+a M, click on CPU/RAM)
#  system.sh ensure          create it if missing / rebuild it if broken (hooks)
#  system.sh repair          the same, skipped if a build is already running (pane hooks)
#  system.sh restart         close and rebuild it
#
#  New Windows Terminal tabs open it (tmux/terminal.zsh autostart); the
#  session-closed hook recreates it; it is left out of tmux-resurrect saves.
# ═══════════════════════════════════════════════════════════════

export TERMINAL_SETUP=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)   # the repo (this file is in its tmux/)
S=system
D=$TERMINAL_SETUP/tmux/system
KEEP="$D/keep.sh"
# Resources: header, CPU, RAM, swap, [GPU], WSL disk, C:, Net, Web
RES_ROWS=8; { command -v nvidia-smi || [[ -x /usr/lib/wsl/lib/nvidia-smi ]]; } &>/dev/null && RES_ROWS=9
# one lock per tmux server, known before the server runs (so `terminal system` with no server and
# the config's own ensure take the same one): the socket's path, as tmux would make it
sock=${TMUX%%,*}
[[ -z $sock ]] && sock=$(tmux display -p '#{socket_path}' 2>/dev/null)
[[ -z $sock ]] && sock=${TMUX_TMPDIR:-/tmp}/tmux-$UID/default
key=${sock//\//_}
run_dir=${XDG_RUNTIME_DIR:-/tmp}; [[ -d $run_dir && -w $run_dir ]] || run_dir=/tmp
LOCK=$run_dir/tmux-system-$UID-$key.lock

build() {
  local py="python3 -I $TERMINAL_SETUP/tmux" sh="${SHELL:-zsh}"
  local info res btop procs ports folders disks clean pkgs updates search pkg hosts hostd keys cont det logs repos repo
  # 1 · info: fastfetch with Resources below it · btop on the right
  tmux ${NOSTART:+-N} new-session -d -s $S -n info -x 200 -y 50 -c "$HOME" "$KEEP $D/info.sh" || return
  info=$(tmux display -p -t "$S:info" '#{pane_id}')
  btop=$(tmux split-window -h -l 42% -t "$info" -c "$HOME" -P -F '#{pane_id}' "$KEEP $D/btop.sh")
  res=$(tmux split-window -v -l $RES_ROWS -t "$info" -c "$HOME" -P -F '#{pane_id}' "$KEEP $D/resources.sh")
  # 2 · monitor: processes and ports (interactive)
  procs=$(tmux new-window -d -t "$S:" -n monitor -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/procs.py")
  ports=$(tmux split-window -h -l 48% -t "$procs" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/ports.py")
  # 3 · disk: what takes the space (like ncdu) │ the disks · what can be cleaned
  folders=$(tmux new-window -d -t "$S:" -n disk -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/disk_folders.py")
  disks=$(tmux split-window -h -l 44% -t "$folders" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/disk_mounts.py")
  clean=$(tmux split-window -v -l 72% -t "$disks" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/disk_cleanup.py")
  # 4 · packages: yours · updates │ search all · details of the highlighted one
  pkgs=$(tmux new-window -d -t "$S:" -n packages -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/packages.py")
  search=$(tmux split-window -h -l 50% -t "$pkgs" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/pkgsearch.py")
  updates=$(tmux split-window -v -l 40% -t "$pkgs" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/updates.py")
  pkg=$(tmux split-window -v -l 55% -t "$search" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/pkginfo.py")
  # 5 · ssh: the hosts of ~/.ssh/config on top · the highlighted one │ your keys and the agent
  hosts=$(tmux new-window -d -t "$S:" -n ssh -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/ssh_hosts.py")
  hostd=$(tmux split-window -v -l 58% -t "$hosts" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/ssh_host.py")
  keys=$(tmux split-window -h -l 46% -t "$hostd" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/ssh_keys.py")
  # 6 · docker: containers (like dps) on top · details + Dockerfile │ live logs
  cont=$(tmux new-window -d -t "$S:" -n docker -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/docker.py")
  det=$(tmux split-window -v -l 62% -t "$cont" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/docker_details.py")
  logs=$(tmux split-window -h -l 52% -t "$det" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/docker_logs.py")
  # 7 · git: your repos on top · the highlighted one below
  repos=$(tmux new-window -d -t "$S:" -n git -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/git_repos.py")
  repo=$(tmux split-window -v -l 58% -t "$repos" -c "$HOME" -P -F '#{pane_id}' "$KEEP $py/git_repo.py")

  local pair
  for pair in "$info=Info" "$res=Resources" "$btop=btop" "$procs=Processes" "$ports=Ports" \
              "$folders=Folders" "$disks=Disks" "$clean=Cleanup" \
              "$pkgs=Packages" "$updates=Updates" "$search=Search" "$pkg=Package" \
              "$hosts=Hosts" "$hostd=Host" "$keys=Keys" \
              "$cont=Containers" "$det=Container" "$logs=Logs" "$repos=Repos" "$repo=Repo"; do
    tmux set -p -t "${pair%%=*}" @label "${pair#*=}"
  done
  local w
  for w in info:󰋽 monitor:󰐰 disk:󰋊 packages:󰏗 ssh:󰣀 docker:󰡨 git:󰊢; do
    tmux set -w -t "$S:${w%%:*}" automatic-rename off \; set -w -t "$S:${w%%:*}" @icon "${w#*:}"
  done
  # When the Info tab changes size (fullscreen, a client of another size…): keep Resources
  # at its height and give btop the boxes that fit (tmux/system/info-fit.sh)
  tmux resize-pane -t "$res" -y $RES_ROWS \
     \; set-hook -w -t "$S:info" window-resized "run-shell -b '$D/info-fit.sh $res $btop $RES_ROWS'"
  "$D/info-fit.sh" "$res" "$btop" "$RES_ROWS"
  # same for the tabs with a list on top: it keeps a useful height (tmux/system/top-fit.sh)
  local fit tab top pct
  for fit in "docker $cont 38" "ssh $hosts 42" "git $repos 42"; do
    read -r tab top pct <<< "$fit"
    tmux set-hook -w -t "$S:$tab" window-resized "run-shell -b '$D/top-fit.sh $top $pct'"
    "$D/top-fit.sh" "$top" "$pct"
  done
  # and Disks keeps the height of its list, Cleanup below gets the rest (tmux/system/disk-fit.sh)
  tmux set-hook -w -t "$S:disk" window-resized "run-shell -b '$D/disk-fit.sh $disks'"
  tmux set -t "$S:" @description "System · info, processes & ports, disk, packages, ssh, docker, git"
  tmux select-window -t "$S:info" \; select-pane -t "$info"
}

# Every labelled pane must be there (extra tabs of your own are fine); anything missing
# (a pane was closed, an old save brought it back without its programs) → rebuild.
NEEDED="Cleanup Container Containers Disks Folders Host Hosts Info Keys Logs Package Packages Ports Processes
        Repo Repos Resources Search Updates btop"
healthy() {
  local have; have=" $(tmux list-panes -s -t "=$S" -F '#{@label}' 2>/dev/null | tr '\n' ' ') "
  local l; for l in $NEEDED; do [[ $have == *" $l "* ]] || return 1; done
}

# Serialise ensure / restart (hooks and new tabs may run them at the same time). The lock
# lives in a subshell so it is released as soon as the work is done, never held by an
# attached client; -w 5 so nothing can ever wait on it for long.
locked() { ( flock -w 5 9 || exit 0; "$@" ) 9>"$LOCK"; }   # another build still running after 5 s: it does it

ensure_now() {
  if tmux has-session -t "=$S" 2>/dev/null; then
    healthy && return 0
    # broken (a pane was closed, or an old save brought it back without its programs):
    # build a fresh copy next to it, then swap names · you stay on the tab you were on
    local was; was=$(tmux display -p -t "$S:" '#W' 2>/dev/null)
    tmux rename-session -t "=$S" "$S-old"
    build
    [[ -n $was ]] && tmux select-window -t "$S:$was" 2>/dev/null
    tmux list-clients -t "$S-old" -F '#{client_name}' | while read -r c; do tmux switch-client -c "$c" -t "=$S"; done
    keep_own_tabs
    tmux kill-session -t "=$S-old"
  else
    build
  fi
}

restart_now() {
  local was; was=$(tmux display -p -t "$S:" '#W' 2>/dev/null)
  tmux rename-session -t "=$S" "$S-old" 2>/dev/null
  build
  [[ -n $was ]] && tmux select-window -t "$S:$was" 2>/dev/null
  tmux list-clients -t "$S-old" -F '#{client_name}' 2>/dev/null | while read -r c; do tmux switch-client -c "$c" -t "=$S"; done
  keep_own_tabs
  tmux kill-session -t "=$S-old" 2>/dev/null
}

# Tabs of your own inside the monitor (no pane of theirs is a monitor pane) move to the new
# one instead of going with the old session
keep_own_tabs() {
  local w labels
  tmux list-windows -t "=$S-old" -F '#{window_id}' 2>/dev/null | while read -r w; do
    labels=$(tmux list-panes -t "$w" -F '#{@label}' 2>/dev/null | tr -d '\n')
    [[ -z $labels ]] && tmux move-window -s "$w" -t "$S:" 2>/dev/null
  done
}

# Session descriptions (picker → Describe…) live in ~/.tmux/descriptions.tsv; put them back
# on the sessions after a tmux restart so the session tree shows them too.
sync_descriptions() {
  local name text
  [[ -r ~/.tmux/descriptions.tsv ]] || return 0
  while IFS=$'\t' read -r name text; do
    [[ -n $name && -n $text ]] && tmux has-session -t "=$name" 2>/dev/null \
      && tmux set -t "$name:" @description "$text"
  done < ~/.tmux/descriptions.tsv
}

ensure() { locked ensure_now; sync_descriptions; }

# Hooks run these while tmux may be shutting down (kill-server closes every session, and
# session-closed fires): they must never start a new, invisible server. NOSTART → `tmux -N`.
server_up() { tmux -N start-server 2>/dev/null; }   # -N: only asks, never starts one

case $1 in
  ensure|-d) server_up || exit 0; NOSTART=1; ensure ;;
  # from hooks (a pane / tab of system was closed): never queue up behind a build in progress
  repair)    server_up || exit 0; NOSTART=1; ( flock -n 9 || exit 0; ensure_now ) 9>"$LOCK" ;;
  restart)   server_up || exit 0; NOSTART=1; locked restart_now ;;
  go)        NOSTART=1; ensure; tmux switch-client ${2:+-c "$2"} -t "=$S" ;;
  ""|open)   if ! tmux show -gv exit-empty &>/dev/null; then tmux start-server; fi
             ensure
             if [[ -n $TMUX ]]; then tmux switch-client -t "=$S"; else tmux attach-session -t "=$S"; fi ;;
  *)         echo "usage: system.sh [open|go <client>|ensure|restart]" >&2; exit 1 ;;
esac
