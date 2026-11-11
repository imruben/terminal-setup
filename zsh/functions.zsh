# Every step runs even if one before failed; the end says which ones did
_maint_step() {
  local title=$1; shift
  print -P "%B%F{blue}==>%f $title%b"
  "$@" || _maint_failed+=($title)
}

# update / clean: every package manager there is on this system (apt, snap, Homebrew),
# plus the zsh and tmux plugins. macOS updates itself from System Settings.
update() {
  local -a _maint_failed
  (( $+commands[apt-get] )) && \
    _maint_step "apt" eval 'sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove --purge -y'
  (( $+commands[snap] )) && _maint_step "snap" sudo snap refresh
  (( $+commands[brew] )) && _maint_step "brew" eval 'brew update && brew upgrade'
  [[ -d ~/.zsh/plugins/fzf-tab ]] && _maint_step "fzf-tab" git -C ~/.zsh/plugins/fzf-tab pull -q
  # tmux plugins (tpm reads the list from the running server)
  [[ -x ~/.tmux/plugins/tpm/bin/update_plugins ]] && tmux info &>/dev/null \
    && _maint_step "tmux plugins" ~/.tmux/plugins/tpm/bin/update_plugins all
  tmux set -g @pkgs-changed "$(date +%s%N)" 2>/dev/null      # the tmux Packages / Updates panes re-read
  if (( $#_maint_failed )); then
    echo "⚠️  Update finished with errors in: ${(j:, :)_maint_failed}"; return 1
  fi
  echo "✅ Update Completed"
}

clean() {
  local -a _maint_failed
  (( $+commands[apt-get] )) && _maint_step "apt" eval '
    dpkg -l | awk "/^rc/ {print \$2}" | xargs -r sudo apt purge -y &&
    sudo apt autoremove --purge -y && sudo apt autoclean -y && sudo apt clean -y'
  (( $+commands[journalctl] )) && \
    _maint_step "journal" eval 'sudo journalctl --vacuum-time=7d --vacuum-size=50M 2>/dev/null; true'
  # snap keeps the previous revision of every snap (disabled): remove them
  (( $+commands[snap] )) && _maint_step "snap" eval '
    snap list --all | awk "/disabled/ {print \$1, \$3}" | while read -r name rev; do
      sudo snap remove "$name" --revision="$rev"
    done'
  # brew: dependencies nothing needs any more, old versions and the download cache
  (( $+commands[brew] )) && _maint_step "brew" eval 'brew autoremove && brew cleanup --prune=all'
  (( $+commands[docker] )) && _maint_step "docker build cache" eval 'docker builder prune -f 2>/dev/null; true'
  tmux set -g @pkgs-changed "$(date +%s%N)" 2>/dev/null
  if (( $#_maint_failed )); then
    echo "⚠️  Clean up finished with errors in: ${(j:, :)_maint_failed}"; return 1
  fi
  echo "✅ Clean Up Completed"
}

# Docker Compose: interpolate ${VARS} from .env + .env.local when both exist in cwd
_compose_env_files() {
  if [[ -f .env && -f .env.local ]]; then
    export COMPOSE_ENV_FILES=.env,.env.local
  elif [[ $COMPOSE_ENV_FILES == .env,.env.local ]]; then    # only the value set here: yours stays
    unset COMPOSE_ENV_FILES
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook chpwd _compose_env_files
_compose_env_files

# Listening TCP sockets, in `ss -tlnpH` form, also on macOS (from lsof)
_listening_tcp() {
  if (( $+commands[ss] )); then
    ss -tlnpH 2>/dev/null
  else
    lsof -nP -iTCP -sTCP:LISTEN -F pcn 2>/dev/null | awk '
      /^p/ { pid = substr($0, 2) }  /^c/ { cmd = substr($0, 2) }
      /^n/ { print "LISTEN 0 0 " substr($0, 2) " *:* users:((\"" cmd "\",pid=" pid "))" }'
  fi
}

ports() {
  emulate -L zsh
  local filter="$1" TAB=$'\t'

  # Docker published ports -> container name
  local -A dmap
  if (( $+commands[docker] )) && docker info &>/dev/null; then
    local cname plist p
    while IFS='|' read -r cname plist; do
      for p in ${(s:, :)plist}; do
        [[ "$p" == *"->"* ]] || continue
        p=${p%%"->"*}; p=${p##*:}
        dmap[$p]="$cname"
      done
    done < <(docker ps --format '{{.Names}}|{{.Ports}}')
  fi

  local -a rows
  rows=("${(@f)$(_listening_tcp | awk '
    {
      a=$4; port=a; sub(/.*:/, "", port); sub(/:[^:]*$/, "", a); sub(/%.*/, "", a)
      proc="-"; pid="-"
      if (match($0, /\("[^"]+"/)) proc=substr($0, RSTART+2, RLENGTH-3)
      if (match($0, /pid=[0-9]+/)) pid=substr($0, RSTART+4, RLENGTH-4)
      k=port "\t" pid "\t" proc
      if (!(k in addrs)) addrs[k]=a
      else if (index(" " addrs[k] " ", " " a " ") == 0) addrs[k]=addrs[k] " " a
    }
    END { for (k in addrs) print k "\t" addrs[k] }' | sort -t$'\t' -k1,1n)}")

  local B=$'\e[1m' Y=$'\e[33m' C=$'\e[36m' R=$'\e[0m'
  local -a out=("PORT${TAB}PID${TAB}PROCESS${TAB}ADDRESS") colors=("$B") f
  local row port pid proc addr exposed=0
  for row in $rows; do
    f=("${(@ps:\t:)row}")
    port=$f[1] pid=$f[2] proc=$f[3] addr=$f[4]
    [[ -n "${dmap[$port]}" ]] && proc="docker:${dmap[$port]}"
    [[ -n "$filter" && "${(L)port} $pid ${(L)proc}" != *${(L)filter}* ]] && continue
    out+=("$port${TAB}$pid${TAB}$proc${TAB}$addr")
    if [[ "$proc" == docker:* ]]; then
      colors+=("$C")
    elif [[ "$addr" == *(0.0.0.0|\[::\]|\*)* ]]; then
      colors+=("$Y"); (( exposed++ ))
    else
      colors+=("")
    fi
  done

  (( $#out > 1 )) || { print "No listening ports."; return 0 }

  local i=1 line
  print -rl -- $out | column -t -s $TAB | while IFS= read -r line; do
    print -r -- "${colors[i]}${line}${R}"
    (( i++ ))
  done
  print
  local n=$(( $#out - 1 ))
  print -r -- "$n port$( (( n == 1 )) || print s) · $exposed exposed on all interfaces"
}

killport() {
  [[ -z "$1" ]] && { echo "Usage: killport <port>"; return 1 }
  local -a pids
  if [[ $OSTYPE != darwin* ]] && (( $+commands[fuser] )); then
    pids=(${=$(fuser "$1/tcp" 2>/dev/null)})
  else                                           # macOS (its BSD fuser does not take PORT/tcp)
    pids=(${(f)"$(lsof -t -nP -iTCP:$1 -sTCP:LISTEN 2>/dev/null)"})
  fi
  if (( ! $#pids )); then
    # without sudo, the programs of other users (root: docker-proxy, nginx…) cannot be seen
    if _listening_tcp | awk -v p="$1" '{ a = $4; sub(/.*:/, "", a); if (a == p) f = 1 } END { exit !f }'; then
      echo "Port $1 is in use by another user's program (root?): see it with  sudo ss -tlnp 'sport = :$1'"
      return 1
    fi
    echo "Port $1 is not in use"; return 0
  fi

  ps -o pid,user,args -p ${(j:,:)pids}
  echo
  read -q "?Kill these processes? [y/N] " || { echo; echo "Cancelled"; return 0 }
  echo
  kill -9 $pids && echo "✅ Port $1 freed"
}

# Docker
dps() {
  emulate -L zsh
  setopt local_options

  local ps_flags="" show_stats=1 arg
  for arg in "$@"; do
    case "$arg" in
      -a|--all)   ps_flags="-a" ;;
      -q|--quick) show_stats=0 ;;
      -h|--help)  print "Usage: dps [-a|--all] [-q|--quick]"; return 0 ;;
      *)          print "❌ Unknown option: $arg"; return 1 ;;
    esac
  done

  docker info &>/dev/null || { print "❌ Docker daemon is not responding"; return 1 }
  local -a rows
  rows=("${(@f)$(
    docker ps $ps_flags --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Networks}}|{{.Ports}}' \
      | sed -E 's/, \[::\]:[0-9]+->[0-9]+\/(tcp|udp)//g; s/0\.0\.0\.0://g; s#/tcp##g' \
      | awk -F'|' 'BEGIN{OFS="|"} {for(i=1;i<=NF;i++) if($i=="") $i="-"; print}' \
      | sort -t'|' -k1,1
  )}")
  [[ -n "${rows[1]}" ]] || { print "No containers."; return 0 }

  local -a imgs=() names=() f
  local row
  for row in "${rows[@]}"; do
    f=("${(@s.|.)row}")
    names+=("${f[1]}")
    imgs+=("${f[2]}")
  done

  local -A cpu mem
  local -F total_mib=0 total_cpu=0
  if (( show_stats )); then
    local n c m usage limit num unit
    local -a mparts
    while IFS='|' read -r n c m; do
      cpu[$n]="$c"
      mparts=("${(@s:/:)m}")            # "123MiB / 7.667GiB"
      usage="${mparts[1]// /}"
      limit="${mparts[2]// /}"
      mem[$n]="${usage}/${limit:-?}"
      num="${usage%%[A-Za-z]*}"
      unit="${usage##*[0-9.]}"
      case "$unit" in
        B)   total_mib=$(( total_mib + num / 1048576.0 )) ;;
        KiB) total_mib=$(( total_mib + num / 1024.0 )) ;;
        MiB) total_mib=$(( total_mib + num )) ;;
        GiB) total_mib=$(( total_mib + num * 1024 )) ;;
      esac
      total_cpu=$(( total_cpu + ${c%\%} ))
    done < <(docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}' 2>/dev/null)
  fi

  local -A arch
  local img
  for img in ${(u)imgs}; do
    arch[$img]="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$img" 2>/dev/null)"
  done

  local host_arch
  case "$(uname -m)" in
    arm64|aarch64) host_arch=arm64 ;;
    x86_64|amd64)  host_arch=amd64 ;;
    *)             host_arch="$(uname -m)" ;;
  esac

  local -a restarting=()
  local rn rc
  while IFS='|' read -r rn rc; do
    (( rc > 0 )) && restarting+=("${rn#/}(${rc})")
  done < <(docker inspect --format '{{.Name}}|{{.RestartCount}}' "${names[@]}" 2>/dev/null)

  local TAB=$'\t'
  local -a out=("NAME${TAB}STATUS${TAB}CPU${TAB}MEM${TAB}ARCH${TAB}NETWORKS${TAB}PORTS")
  local -a emulated=()
  local name bare
  for row in "${rows[@]}"; do
    f=("${(@s.|.)row}")
    name="${f[1]}"
    bare="${arch[${f[2]}]##*/}"
    [[ -n "$bare" && "$bare" != "$host_arch" ]] && emulated+=("$name")
    out+=("$name${TAB}${f[3]}${TAB}${cpu[$name]:--}${TAB}${mem[$name]:--}${TAB}${bare:-?}${TAB}${f[4]}${TAB}${f[5]}")
  done

  local B=$'\e[1m' Y=$'\e[33m' G=$'\e[32m' RD=$'\e[31m' R=$'\e[0m'
  local line first=1
  print -rl -- "${out[@]}" | column -t -s $'\t' | while IFS= read -r line; do
    if (( first )); then
      first=0
      print -r -- "${B}${line}${R}"
    elif [[ "$line" == *"(unhealthy)"* || "$line" == *Restarting* || "$line" == *Exited* ]]; then
      print -r -- "${RD}${line}${R}"
    elif (( ${emulated[(Ie)${line%% *}]} )); then
      print -r -- "${Y}${line}${R}"
    elif [[ "$line" == *"(healthy)"* ]]; then
      print -r -- "${G}${line}${R}"
    else
      print -r -- "$line"
    fi
  done

  local -a notes=("${#rows} containers")
  if (( show_stats )); then
    local mem_str
    if (( total_mib >= 1024 )); then
      mem_str=$(printf '%.2fGiB' $(( total_mib / 1024.0 )))
    else
      mem_str=$(printf '%.0fMiB' $total_mib)
    fi
    notes+=("CPU $(printf '%.2f%%' $total_cpu)" "MEM $mem_str")
  fi
  (( ${#emulated} )) && notes+=("${#emulated} emulated")

  print
  print -r -- "${(j: · :)notes}"
  (( ${#restarting} )) && print -r -- "${RD}⚠️  restarts: ${(j:, :)restarting}${R}"
}

dsh() {
  emulate -L zsh

  local -a user_flag=(-u "$(id -u):$(id -g)")
  local container arg
  for arg in "$@"; do
    case "$arg" in
      -u|--user)  user_flag=(-u "$(id -u):$(id -g)") ;;
      -r|--root)  user_flag=(-u 0) ;;
      -h|--help)  print "Usage: dsh [-u|--user (default)] [-r|--root] [container]"; return 0 ;;
      -*)         print "❌ Unknown option: $arg"; return 1 ;;
      *)          container="$arg" ;;
    esac
  done

  docker info &>/dev/null || { print "❌ Docker daemon is not responding"; return 1 }
  if [[ -z "$container" ]]; then
    container=$(docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort \
      | fzf --delimiter='\t' --with-nth=1.. --prompt='container> ' \
            --preview 'docker logs --tail 50 {1} 2>&1' | cut -f1)
    [[ -n "$container" ]] || return 0
  fi

  docker exec -it $user_flag "$container" sh -c \
    'if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi'
}

fkill() {
  emulate -L zsh

  local sig="TERM"
  [[ "$1" == -* ]] && { sig="${1#-}"; shift }
  [[ "$sig" == (h|-help) ]] && { print "Usage: fkill [-SIGNAL] [query]   (default: -TERM)"; return 0 }

  local -a pids sort=(--sort=-%cpu)
  [[ $OSTYPE == darwin* ]] && sort=(-r)          # BSD ps: -r sorts by CPU
  pids=(${(f)"$(ps -u "$USER" -o pid=,etime=,%cpu=,%mem=,args= $sort \
    | fzf -m --query="$*" --header="TAB to select multiple · signal: $sig" \
          --preview 'ps -o pid,ppid,user,lstart,args -p {1}' \
          --preview-window=down,4,wrap \
    | awk '{print $1}')"})
  (( $#pids )) || return 0

  sig=${${(U)sig}#SIG}                           # -term, -SIGTERM → TERM · -9 stays 9
  if [[ $sig == <-> ]]; then kill -$sig $pids; else kill -s $sig $pids; fi \
    && print "✅ Sent ${${sig:#<->}:+SIG}$sig to: ${(j:, :)pids}"
}

# Packages you installed yourself: apt (minus the base WSL image), snap apps and brew
# formulae installed on request · same list and notes as the tmux system Packages tab
# (both ask tmux/pkgsrc.py). Notes: ~/.apt-notes.tsv (apt by name, others as snap:NAME).
_pkgsrc() { python3 -I $TERMINAL_SETUP/tmux/pkgsrc.py "$@" }

# NAME or SOURCE:NAME → "source<TAB>name<TAB>version<TAB>description" lines where it is installed
_installed_packages_find() {
  local src=${1%%:*} name=${1#*:}
  if [[ $1 == *:* ]] && (( ${${(f)"$(_pkgsrc sources)"}[(Ie)$src]} )); then
    _pkgsrc find $name | awk -F'\t' -v s=$src '$1 == s'
  else
    _pkgsrc find $1
  fi
}

installed-packages() {
  emulate -L zsh

  local base=~/.apt-base.txt notes=~/.apt-notes.tsv rebuild=0 pkg only p d k s n v r
  local -a hits
  local -A note
  [[ -r $notes ]] && while IFS=$'\t' read -r p d; do
    [[ -n $p ]] && note[$p]="$d"
  done < $notes

  while (( $# )); do
    case "$1" in
      -r|--rebuild) rebuild=1; shift ;;
      -s|--source)
        [[ -n $2 ]] && (( ${${(f)"$(_pkgsrc sources)"}[(Ie)$2]} )) \
          || { print "❌ Source must be one of: ${(j:, :)${(f)"$(_pkgsrc sources)"}}"; return 1 }
        only=$2; shift 2 ;;
      -n|--note)
        [[ -n $pkg ]] || { print "Usage: installed-packages <package> --note [reason]"; return 1 }
        shift
        if (( $# )); then
          note[$pkg]="${*//$'\t'/ }"
          print "✅ Note saved for $pkg"
        else
          unset "note[$pkg]"
          print "✅ Note removed for $pkg"
        fi
        for k in ${(ko)note}; do print -r -- "$k"$'\t'"${note[$k]}"; done > $notes
        (( $+commands[tmux] )) && tmux set -g @pkgs-changed "$(date +%s%N)" 2>/dev/null   # tmux panes too
        return 0 ;;
      -h|--help)
        print "Usage: installed-packages [package] [options]"
        print "  installed-packages                      list packages you installed (apt, snap, brew)"
        print "  installed-packages -s <source>          only apt, snap or brew"
        print "  installed-packages <pkg>                show a single package (or snap:<pkg>, brew:<pkg>)"
        print "  installed-packages <pkg> -n [reason]    set why it was installed (no reason = remove)"
        print "  installed-packages -r, --rebuild        regenerate the apt base list (what the system came with)"
        return 0 ;;
      -*) print "❌ Unknown option: $1"; return 1 ;;
      *)
        [[ -z $pkg ]] || { print "❌ Only one package at a time"; return 1 }
        hits=(${(f)"$(_installed_packages_find $1)"})
        (( $#hits )) || { print "❌ Package not installed: $1"; return 1 }
        (( $#hits == 1 )) || {
          print "❌ $1 is installed from ${(j: and :)${hits%%$'\t'*}}: say which, e.g. ${hits[2]%%$'\t'*}:${1#*:}"
          return 1 }
        s=${hits[1]%%$'\t'*}; p=${${hits[1]#*$'\t'}%%$'\t'*}
        pkg=$([[ $s == apt ]] && print -r -- $p || print -r -- "$s:$p")   # the note key
        shift ;;
    esac
  done

  # 1. --rebuild: the apt base list again (otherwise pkgsrc.py makes it the first time)
  if (( rebuild )); then
    _pkgsrc base || return 1
    print
  fi

  # 2. Rows: source, name, version, description (all of them, one source, or the one requested)
  local -a rows
  if [[ -n $pkg ]]; then
    rows=($hits)
  else
    rows=(${(f)"$(_pkgsrc mine $only)"})
  fi
  (( $#rows )) || { print "No packages installed by you${only:+ from $only}."; return 0 }

  # 3. Column widths (WHY column only if there are notes, max 40 chars)
  local -i w=7 nw=0 maxd noted=0
  local -A key count
  for r in $rows; do
    s=${r%%$'\t'*}; p=${${r#*$'\t'}%%$'\t'*}
    k=$([[ $s == apt ]] && print -r -- $p || print -r -- "$s:$p")
    key[$s:$p]=$k
    (( count[$s]++ ))
    (( $#p > w )) && w=$#p
    (( ${#note[$k]} > nw )) && nw=${#note[$k]}
    [[ -n ${note[$k]} ]] && (( noted++ ))
  done
  (( nw > 40 )) && nw=40
  (( nw > 0 && nw < 3 )) && nw=3
  maxd=$(( ${COLUMNS:-100} - w - 3 - 4 - 3 - (nw ? nw + 3 : 0) ))
  (( maxd < 20 )) && maxd=20

  # 4. Output
  local B=$'\e[1m' C=$'\e[36m' Y=$'\e[33m' D=$'\e[2m' R=$'\e[0m' h=PACKAGE hw=WHY f
  local -A colour=(apt $'\e[34m' snap $'\e[38;5;208m' brew $'\e[33m')
  if (( nw )); then
    print -r -- "${B}${(r:w:)h}   FROM   ${(r:nw:)hw}   DESCRIPTION${R}"
  else
    print -r -- "${B}${(r:w:)h}   FROM   DESCRIPTION${R}"
  fi
  for r in $rows; do
    s=${r%%$'\t'*}; r=${r#*$'\t'}; p=${r%%$'\t'*}; r=${r#*$'\t'}; v=${r%%$'\t'*}; d=${r#*$'\t'}
    d=${d:--}
    (( $#d > maxd )) && d="${d[1,maxd-1]}…"
    f="${colour[$s]}${(r:4:)s}${R}"
    if (( nw )); then
      n=${note[${key[$s:$p]}]}
      (( $#n > nw )) && n="${n[1,nw-1]}…"
      print -r -- "${C}${(r:w:)p}${R}   $f   ${Y}${(r:nw:)n}${R}   ${D}${d}${R}"
    else
      print -r -- "${C}${(r:w:)p}${R}   $f   ${D}${d}${R}"
    fi
  done

  if [[ -n $pkg ]]; then
    print -r -- "${D}version ${v}${note[$pkg]:+ · why: ${note[$pkg]}}${R}"
  else
    local -a b=(${(f)"$(<$base 2>/dev/null)"}) per
    for s in apt snap brew; do (( count[$s] )) && per+=("$s ${count[$s]}"); done
    print
    print -r -- "${#rows} package$( (( $#rows == 1 )) || print s) (${(j: · :)per}) · $noted with notes${b:+ · ${#b} apt ones in the base image}"
  fi
}

_installed-packages() {
  local p d s v
  local -a items opts
  local -A note
  [[ -r ~/.apt-notes.tsv ]] && while IFS=$'\t' read -r p d; do
    note[$p]="$d"
  done < ~/.apt-notes.tsv

  if [[ $words[CURRENT-1] == (-s|--source) ]]; then
    compadd -- ${(f)"$(_pkgsrc sources 2>/dev/null)"}
  elif (( CURRENT == 2 )) || { [[ $words[2] == (-s|--source) ]] && (( CURRENT == 4 )) }; then
    if [[ $PREFIX == -* ]]; then
      opts=('-s:only one source (apt, snap, brew)' '--source:only one source (apt, snap, brew)'
            '-r:regenerate the apt base package list' '--rebuild:regenerate the apt base package list'
            '-h:show help' '--help:show help')
      _describe -t options option opts
    else
      # apt packages by name, the others as snap:NAME / brew:NAME (the note key)
      while IFS=$'\t' read -r s p v d; do
        [[ $s == apt ]] || p="$s:$p"
        items+=("${p//:/\\:}:${note[$p]:-$d}")
      done < <(_pkgsrc mine 2>/dev/null)
      _describe -t packages package items
    fi
  elif (( CURRENT == 3 )) && [[ $words[2] != -* ]]; then
    opts=('-n:set why it was installed' '--note:set why it was installed')
    _describe -t options option opts
  elif (( CURRENT == 4 )) && [[ $words[3] == (-n|--note) && -n ${note[$words[2]]} ]]; then
    compadd -Q -- "${(qq)note[$words[2]]}"
  fi
}
(( $+functions[compdef] )) && compdef _installed-packages installed-packages

# vps [host]: ssh to your server. The address and user are not here: they are a `Host`
# entry in ~/.ssh/config, on this PC only (default name `vps`, or TERMINAL_VPS in ~/.zshrc).
# Inside tmux it opens in its own window, named after the host.
vps() {
  local host=${1:-${TERMINAL_VPS:-vps}}
  # not configured: ssh would just use the name itself as the address
  if [[ $(ssh -G "$host" 2>/dev/null | awk '$1 == "hostname" {print $2}') == $host ]]; then
    print -u2 "vps: no 'Host $host' in ~/.ssh/config. Add one, e.g.:"
    print -u2 "  Host $host\n    HostName <ip>\n    User <user>"
    return 1
  fi
  if [[ -n $TMUX ]]; then
    tmux new-window -n "$host" "ssh $host"
  else
    ssh "$host"
  fi
}

# every shortcut, searchable (tmux/guide.zsh) · `keys git` opens it searching for git
keys() { $TERMINAL_SETUP/tmux/guide.zsh "$@" }

# tmux session manager (tmux/terminal.zsh) · `terminal help`
terminal() { $TERMINAL_SETUP/tmux/terminal.zsh "$@" }

_terminal() {
  if (( CURRENT == 2 )); then
    local -a cmds=(
      'open:open or create a session' 'list:list sessions' 'rename:rename a session'
      'kill:kill a session' 'kill-all:kill every session (the system monitor stays)' 'guide:searchable tmux guide'
      'system:the system monitor' 'files:every file the install put here, and what it is for' 'help:show help')
    _describe command cmds
  elif (( CURRENT == 3 )) && [[ $words[2] == (open|o|kill|k|rename|mv) ]]; then
    local -a sessions=(${(f)"$($TERMINAL_SETUP/tmux/terminal.zsh _names)"})
    _describe session sessions
  elif (( CURRENT == 4 )) && [[ $words[2] == (open|o) ]]; then
    _directories
  fi
}
(( $+functions[compdef] )) && compdef _terminal terminal
