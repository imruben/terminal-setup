#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════════
#  terminal · tmux session manager
#  Used by: the `terminal` shell function (zsh/functions.zsh), the Ctrl+a s
#  popup and `terminal`. New terminal windows / tabs open the start session:
#  the one chosen with `terminal start NAME` (or Ctrl+s in the session picker),
#  kept in ~/.tmux/start-session · without one, the `system` monitor (tmux/system.sh).
#  Sessions are created by hand: no project scanning.
#
#  Config (env vars):
#    TERMINAL_NO_AUTOSTART=1  do not open tmux in new tabs (in ~/.zshrc, above the terminal-setup line)
# ═══════════════════════════════════════════════════════════════

emulate -L zsh
export TERMINAL_SETUP=${0:A:h:h}            # the repo (this file is in its tmux/)
setopt extended_glob

B=$'\e[1m' D=$'\e[2m' C=$'\e[36m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' M=$'\e[35m' X=$'\e[0m'
SELF=${0:A}
TAB=$'\t'

# ─────────────── Helpers ───────────────

ok()   { print -r -- "${G}✔${X} $*" }
fail() { print -r -- "${R}✖${X} $*" >&2 }

# Read a line from the user: ask <prompt> [default]
ask() {
  local reply
  print -n -- "${C}$1${X} ${2:+${D}[$2]${X} }" > /dev/tty
  read -r reply < /dev/tty
  print -r -- "${reply:-$2}"
}

# Keep an error on screen until a key is pressed (the popup would close otherwise)
pause() {
  print -n -- "${D}press any key${X}" > /dev/tty
  read -sk < /dev/tty
}

# y/n confirmation, defaults to no
confirm() {
  print -n -- "${Y}$1${X} ${D}(y/N)${X} " > /dev/tty
  read -q < /dev/tty; local rc=$?
  print > /dev/tty
  return $rc
}

server_running() { tmux show -gv exit-empty &>/dev/null }
session_exists() { tmux has-session -t "=$1" 2>/dev/null }
session_names()  { tmux ls -F '#{session_name}' 2>/dev/null }
current_session() { [[ -n $TMUX ]] && tmux display -p '#S' 2>/dev/null }

# tmux does not allow "." or ":" in session names; spaces around go, and a leading "-"
# would be read as an option
clean_name() {
  local n=${${1##[[:space:]]#}%%[[:space:]]#}
  n=${${n//[.:]/-}//[[:space:]]##/-}
  print -r -- ${n##-#}
}

# ─────────────── Start session (new terminals open it) ───────────────
# ~/.tmux/start-session: "name<TAB>folder" (the folder to create it in when it is not running)
START_FILE=~/.tmux/start-session

start_get() {                 # prints "name<TAB>folder", or nothing (= the system monitor)
  [[ -r $START_FILE ]] || return 0
  local line; IFS= read -r line < $START_FILE
  [[ -n ${line%%$TAB*} && ${line%%$TAB*} != system ]] && print -r -- "$line"
}

start_set() {                 # start_set <name> [folder] · system (or nothing) = back to the monitor
  local name=$(clean_name "$1") dir=${2:-}
  if [[ -z $name || $name == system ]]; then
    rm -f $START_FILE; return
  fi
  [[ -z $dir ]] && session_exists "$name" && dir=$(tmux display -p -t "=$name:" '#{session_path}' 2>/dev/null)
  [[ -z $dir ]] && dir=$PWD
  [[ $dir == '~'(/*|) ]] && dir=$HOME${dir#\~}
  mkdir -p ${START_FILE:h}
  print -r -- "$name$TAB$dir" > $START_FILE
}

start_renamed() {             # the start session was renamed: follow it
  local line=$(start_get)
  [[ ${line%%$TAB*} == $1 ]] && print -r -- "$2$TAB${line#*$TAB}" > $START_FILE
}

start_cmd() {
  case $1 in
    "")
      local line=$(start_get)
      if [[ -z $line ]]; then
        print -r -- "New terminals open the ${B}system${X} monitor ${D}(terminal start NAME changes it)${X}"
      else
        local name=${line%%$TAB*} dir=${line#*$TAB}
        print -r -- "New terminals open ${B}$name${X} ${D}· created in ${dir/#$HOME/~} when it is not running"
        print -r -- "${D}terminal start system goes back to the monitor${X}"
      fi ;;
    -r|--reset|reset|system)
      start_set system; ok "new terminals open the system monitor" ;;
    *)
      start_set "$1" "$2" || return
      local line=$(start_get)
      ok "new terminals open ${B}${line%%$TAB*}${X} ${D}(created in ${${line#*$TAB}/#$HOME/~} when it is not running)${X}" ;;
  esac
}

# a closed session's description must not pass to a new session with the same name
forget_description() {
  local f=~/.tmux/descriptions.tsv
  [[ -f $f ]] && awk -F'\t' -v n="$1" '$1 != n' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
}

# rename_session <old> <new>: also moves its description (picker → Describe…). The system
# monitor keeps its name: tmux/system.sh finds it by it (and would build a second one).
rename_session() {
  local old=$1 new=$(clean_name "$2") f=~/.tmux/descriptions.tsv
  [[ -z $new || $new == $old ]] && return 0
  [[ $old == system || $new == system ]] && { fail "the system monitor keeps its name"; return 1 }
  tmux rename-session -t "=$old" -- "$new" || return
  start_renamed "$old" "$new"
  [[ -f $f ]] && awk -F'\t' -v o="$old" -v n="$new" 'BEGIN { OFS = FS } $1 == o { $1 = n } { print }' "$f" > "$f.tmp" \
    && mv "$f.tmp" "$f"
  ok "$old → ${B}$new${X}"
}

# ─────────────── Open / create ───────────────

# open_session <name> [dir] — attach, or switch when already inside tmux.
# New sessions start in <dir> (default: the current folder).
open_session() {
  local name=$(clean_name "$1") dir=${2:-$PWD}
  [[ -z $name ]] && return 1

  if ! session_exists "$name"; then
    [[ $dir == '~'(/*|) ]] && dir=$HOME${dir#\~}   # expand a typed ~
    [[ -d $dir ]] || { fail "folder not found: $dir"; return 1 }
    tmux new-session -d -s "$name" -c "$dir" || return 1
  fi

  if [[ -n $TMUX ]]; then
    tmux switch-client -t "=$name"
  else
    tmux attach-session -t "=$name"
  fi
}

# Ask for the folder of a new session, then open it
new_session() {
  local name=$(clean_name "$1")
  [[ -z $name ]] && return 1
  session_exists "$name" && { open_session "$name"; return }
  open_session "$name" "$(ask 'Folder:' "${PWD/#$HOME/~}")"
}

# ─────────────── Picker (fzf) ───────────────

# One line per entry: kind <TAB> name <TAB> what fzf shows
picker_lines() {
  local name wins att dir here=$(current_session)
  print -r -- "new${TAB}${TAB}${G}+${X} new session ${D}· type a name, then Enter${X}"

  while IFS=$TAB read -r name wins att dir; do
    [[ -z $name ]] && continue
    local mark="${D}○${X}"
    (( att > 0 )) && mark="${G}●${X}"
    [[ $name == $here ]] && mark="${M}▶${X}"
    print -r -- "session${TAB}${name}${TAB}${mark} ${B}${name}${X}  ${D}${wins} win · ${dir/#$HOME/~}${X}"
  done < <(tmux ls -F "#{session_name}${TAB}#{session_windows}${TAB}#{session_attached}${TAB}#{session_path}" 2>/dev/null)
}

preview() {
  local kind=$1 name=$2
  case $kind in
    session)
      tmux list-windows -t "=$name" -F "#{?window_active,${M}▶${X},${D}·${X}} #I #W ${D}(#{window_panes} panes)${X}" 2>/dev/null
      print -r -- "${D}────────────────────────────────${X}"
      tmux capture-pane -ep -t "=$name:" 2>/dev/null ;;
    *)
      print -r -- "${G}${B}New session${X}"; print
      print -r -- "Type a name and press Enter, then choose its folder"
      print -r -- "${D}(Enter keeps the current one: ${PWD/#$HOME/~})${X}" ;;
  esac
}

pick() {
  # tmux/sessions.py: hover, preview, rename / close buttons (close asks first).
  # The fzf picker below is the fallback when python3 is missing.
  if (( $+commands[python3] )); then
    python3 -I $TERMINAL_SETUP/tmux/sessions.py
    return
  fi

  if ! (( $+commands[fzf] )); then
    session_names | sed 's/^/  · /'
    new_session "$(ask 'Session name:' main)"; return
  fi

  local out rc query key line kind name
  local -a lines parts
  while true; do
    # --height=100% overrides a --height in FZF_DEFAULT_OPTS (it would shrink the popup)
    out=$(picker_lines | fzf --ansi --delimiter=$TAB --with-nth=3 --height=100% \
            --layout=reverse --border=rounded --border-label=" terminal " \
            --prompt="session ❯ " --pointer="▶" --gutter=" " --info=inline-right \
            --header="enter open · ctrl-n new · ctrl-r rename · ctrl-x kill · esc close" \
            --preview="$SELF _preview {1} {2}" \
            --preview-window=right,55%,border-left \
            --print-query --expect=ctrl-n,ctrl-r,ctrl-x)
    rc=$?
    (( rc == 130 || rc == 2 )) && return 1         # esc / error

    lines=("${(@f)out}")
    query=$lines[1] key=$lines[2] line=$lines[3]
    parts=("${(@ps:\t:)line}")
    kind=$parts[1] name=$parts[2]

    case $key in
      ctrl-n)
        name=$(ask 'New session name:' "$query")
        [[ -z $name ]] && continue
        new_session "$name" && return
        pause; continue ;;
      ctrl-r)
        [[ $kind == session ]] || continue
        local new=$(ask "Rename ${name} to:")
        [[ -n $new ]] && { rename_session "$name" "$new" || pause }
        continue ;;
      ctrl-x)
        [[ $kind == session ]] || continue
        if [[ $name == system ]]; then           # always there: closing it means rebuilding it
          confirm "The system monitor is always there: restart it?" && $TERMINAL_SETUP/tmux/system.sh restart
          continue
        fi
        if [[ $name == $(current_session) ]] || (( $(tmux display -p -t "=$name" '#{session_attached}' 2>/dev/null) > 0 )); then
          confirm "Session ${name} is in use. Close it and all its windows anyway?" || continue
        else
          confirm "Close session ${name} and all its windows?" || continue
        fi
        tmux kill-session -t "=$name"
        continue ;;
    esac

    case $kind in
      session) open_session "$name" && return ;;
      *)       # "+ new session" line, or Enter with nothing matching
               name=${query:-$(ask 'New session name:')}
               [[ -z $name ]] && continue
               new_session "$name" && return ;;
    esac
    pause
  done
}

# ─────────────── Auto-start (new Windows Terminal tab) ───────────────

# Start the server so continuum restores the last saved sessions, wait for
# them to appear, then open the start session (terminal start), else the system monitor.
autostart() {
  if ! server_running; then
    tmux start-server
    local save
    for save in ~/.tmux/resurrect/last ${XDG_DATA_HOME:-$HOME/.local/share}/tmux/resurrect/last; do
      [[ -e $save ]] && { wait_for_restore; break }
    done
  fi

  # the start session chosen with `terminal start` (created in its folder when it is not
  # running: closed, or not in the last save); the monitor is built meanwhile, in the background
  local line=$(start_get) name dir
  if [[ -n $line ]]; then
    name=${line%%$TAB*} dir=${line#*$TAB}
    ( $TERMINAL_SETUP/tmux/system.sh ensure &>/dev/null & )
    [[ -d $dir ]] || dir=$HOME
    open_session "$name" "$dir" && return
    fail "could not open the start session $name: the system monitor instead"
  fi
  # straight into the system monitor (tmux/system.sh); Ctrl+a s switches session,
  # Ctrl+a d leaves tmux and comes back to this shell
  $TERMINAL_SETUP/tmux/system.sh && return
  print -r -- "${D}Plain shell. Run ${X}${C}terminal${X}${D} any time to open the session picker.${X}"
}

# Wait until the saved sessions are back: tmux-resurrect says so (@restored, its post-restore
# hook), else until restored sessions stop appearing · `system` is not counted (it is built at
# once, before continuum even starts restoring) · at most ~8 s
wait_for_restore() {
  local i count last=-1 stable=0
  print -n -- "${D}Restoring saved sessions…${X}"
  for i in {1..40}; do
    [[ $(tmux show -gqv @restored 2>/dev/null) == 1 ]] && break
    count=$(session_names | grep -cvx system)
    if (( count == last )); then              # nothing new for 1 s (or 2 s with nothing at all): done
      (( ++stable >= (count > 0 ? 5 : 10) )) && break
    else
      stable=0
    fi
    last=$count
    sleep 0.2
  done
  print -n -- "\r\e[K"
}

# ─────────────── List / help ───────────────

list() {
  local name wins att dir here=$(current_session)
  local out=$(tmux ls -F "#{session_name}${TAB}#{session_windows}${TAB}#{session_attached}${TAB}#{session_path}" 2>/dev/null)
  if [[ -z $out ]]; then print -r -- "    ${D}no sessions running${X}"; return; fi
  while IFS=$TAB read -r name wins att dir; do
    local mark="${D}○${X}"
    (( att > 0 )) && mark="${G}●${X}"
    [[ $name == $here ]] && mark="${M}▶${X}"
    printf "    %s %-22s ${D}%s window(s) · %s${X}\n" "$mark" "$name" "$wins" "${dir/#$HOME/~}"
  done <<< "$out"
}

rename() {
  [[ -z $(clean_name "$2") ]] && { fail "usage: terminal rename <old> <new>"; return 1 }
  rename_session "$1" "$2"
}

help() {
  cat <<EOF

  ${B}${C}▌ terminal${X}  ${D}tmux session manager${X}

  ${B}COMMANDS${X}
    ${Y}terminal${X}                       session picker
    ${Y}terminal open${X} <name> [folder]  open, or create it in [folder] ${D}(default: current folder)${X}
    ${Y}terminal list${X}                  list sessions
    ${Y}terminal rename${X} <old> <new>    rename a session
    ${Y}terminal kill${X} <name>           kill a session
    ${Y}terminal kill-all${X}              kill every session (the system monitor stays)
    ${Y}terminal system${X}                system monitor ${D}(info · processes & ports · disk · packages · ssh · docker · git · opens in new tabs)${X}
    ${Y}terminal system restart${X}        rebuild the system monitor
    ${Y}terminal start${X} [name|system]   the session new terminals open ${D}(default: the system monitor)${X}
    ${Y}terminal guide${X}                 tmux guide ${D}(same as Ctrl+a ? inside tmux)${X}
    ${Y}terminal files${X}                 every file the install put on this machine, and what it is for
    ${Y}terminal help${X}                  this panel

  ${B}SESSIONS${X}  ${D}(${G}●${D} attached · ${M}▶${D} current)${X}
$(list)

  ${D}Inside tmux: ${X}${C}Ctrl+a Space${X}${D} quick menu · ${X}${C}Ctrl+a ?${X}${D} guide · ${X}${C}Ctrl+a s${X}${D} this picker${X}
  ${D}New terminals open: ${X}$(local l=$(start_get); print -r -- ${${l%%$TAB*}:-system})${D} · ${X}${C}terminal start NAME${X}${D} changes it (or Ctrl+s in the picker)${X}
  ${D}Disable auto-start: add ${X}export TERMINAL_NO_AUTOSTART=1${D} to ~/.zshrc, above the terminal-setup line${X}

EOF
}

# ─────────────── Entry point ───────────────

case "$1" in
  ""|pick)          pick ;;
  autostart)        autostart ;;
  open|o)           [[ -z $2 ]] && { fail "usage: terminal open <name> [folder]"; exit 1 }
                    open_session "$2" "$3" ;;
  list|ls|l)        print; list; print ;;
  kill|k)           [[ -z $2 ]] && { fail "usage: terminal kill <name>"; exit 1 }
                    session_exists "$2" || { fail "no session called $2"; exit 1 }
                    if [[ $2 == system ]]; then
                      confirm "The system monitor is always there: restart it?" || exit 1
                      $TERMINAL_SETUP/tmux/system.sh restart && ok "system monitor restarted"
                      exit
                    fi
                    if [[ $2 == $(current_session) ]]; then
                      confirm "You are inside ${2}. Close it and all its windows?" || exit 1
                      # this shell dies with the session: queue the picker for this client first
                      tmux run-shell -b -d 0.3 -C "send-keys -K -c '$(tmux display -p '#{client_name}')' C-a s"
                    else
                      confirm "Close session ${2} and all its windows?" || exit 1
                    fi
                    tmux kill-session -t "=$2" && ok "killed ${B}$2${X}" && forget_description "$2" ;;
  # Every session but the system monitor (always there). Saved right away: otherwise the
  # last auto-save (every 5 min) would bring them all back the next time tmux starts.
  kill-all)         local -a all=(${(f)"$(session_names)"}); all=(${all:#system})
                    (( $#all )) || { print -r -- "${D}no sessions running (the system monitor stays)${X}"; exit 0 }
                    confirm "Close ALL ${#all} sessions${TMUX:+, including the one you are in}? (the system monitor stays)" || exit 1
                    local here=$(current_session) save=~/.tmux/plugins/tmux-resurrect/scripts/save.sh
                    for s in ${all:#$here}; do tmux kill-session -t "=$s"; done
                    ok "${#all} sessions closed · saved, so they do not come back on the next start"
                    if (( ${all[(Ie)$here]} )); then
                      # this shell dies with its session: tmux closes it (and saves) once we are gone
                      tmux run-shell -b "tmux kill-session -t '=$here'; TERMINAL_SAVE_EMPTY=1 $save quiet"
                    else
                      TERMINAL_SAVE_EMPTY=1 $save quiet 2>/dev/null     # an empty save is meant here
                    fi ;;
  rename|mv)        [[ -z $3 ]] && { fail "usage: terminal rename <old> <new>"; exit 1 }
                    rename "$2" "$3" ;;
  guide|g)          exec $TERMINAL_SETUP/tmux/guide.zsh ;;
  files|f)          exec bash $TERMINAL_SETUP/install/files.sh ;;
  system|sys)       exec $TERMINAL_SETUP/tmux/system.sh ${2:-open} ;;
  start)            start_cmd "$2" "$3" ;;
  # Ctrl+a $ renamed a session: its description and the start session follow (the old name in @rename-from)
  _renamed)         local old=$(tmux show -gqv @rename-from) new=$(tmux display -p '#S')
                    tmux set -gu @rename-from
                    [[ -n $old && -n $new && $old != $new ]] || exit 0
                    start_renamed "$old" "$new"
                    f=~/.tmux/descriptions.tsv
                    [[ -f $f ]] && awk -F'\t' -v o="$old" -v n="$new" 'BEGIN { OFS = FS } $1 == o { $1 = n } { print }' "$f" > "$f.tmp" \
                      && mv "$f.tmp" "$f" ;;
  help|h|-h|--help) help ;;
  _preview)         preview "$2" "$3" ;;
  _names)           session_names ;;                 # for zsh completion
  *)                fail "unknown command: $1"; help; exit 1 ;;
esac
