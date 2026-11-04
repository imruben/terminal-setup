#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Resources pane of the `system` session (Info tab), redrawn in place every 2 s:
#    header   host · uptime · load · CPUs
#    CPU RAM Swap GPU WSL-disk C:   bars (green / yellow ≥70% / red ≥90%)
#    Net      download / upload speed now, with a short history
#    Web      online?, latency to 1.1.1.1, interface and IP
#  GPU only when nvidia-smi exists (WSL ships it in /usr/lib/wsl/lib).
#  Never prints more lines than the pane has (no scrolling, no flicker).
#  Out of sight (another tab or session, nobody attached) it reads nothing and pings
#  nobody: tmux wakes it with SIGUSR1 when its tab comes into sight (tmuxlink.note_wake).
#  Linux reads /proc; macOS asks ps, vm_stat, sysctl, netstat and route (see the
#  *_read / *_sample functions). bash 3.2 compatible (macOS's /bin/bash).
# ═══════════════════════════════════════════════════════════════

C_TEXT=$'\e[38;2;205;214;244m' C_DIM=$'\e[38;2;108;112;134m' C_TRACK=$'\e[38;2;69;71;90m'
C_OK=$'\e[38;2;166;227;161m' C_WARN=$'\e[38;2;249;226;175m' C_BAD=$'\e[38;2;243;139;168m'
C_HEAD=$'\e[38;2;137;180;250m' C_DOWN=$'\e[38;2;137;220;235m' C_UP=$'\e[38;2;203;166;247m'
B=$'\e[1m' X=$'\e[0m'
SPARK=(▁ ▂ ▃ ▄ ▅ ▆ ▇ █)
NVSMI=$(command -v nvidia-smi || { [[ -x /usr/lib/wsl/lib/nvidia-smi ]] && echo /usr/lib/wsl/lib/nvidia-smi; })
LINUX=0; [[ -r /proc/stat ]] && LINUX=1
IS_WSL=0; [[ -n $WSL_DISTRO_NAME || -e /proc/sys/fs/binfmt_misc/WSLInterop || -e /proc/sys/fs/binfmt_misc/WSLInterop-late ]] && IS_WSL=1
if (( LINUX )); then CORES=$(nproc); else CORES=$(sysctl -n hw.ncpu); fi
# the interface that reaches the internet (it changes with Wi-Fi, a VPN…)
iface() {
  local i
  if (( LINUX )); then
    i=$(ip -o route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") print $(i + 1)}')
    echo "${i:-eth0}"
  else
    i=$(route -n get 1.1.1.1 2>/dev/null | awk '/interface:/ {print $2}')
    echo "${i:-en0}"
  fi
}
IFACE=$(iface)
HOST=${HOSTNAME:-$(hostname)}; HOST=${HOST%%.*}

# Every round runs in this shell: the helpers below leave their answer in $REPLY instead of
# printing it into a $(…), which would fork a subshell (some twenty per round otherwise).
# human <bytes> → 2254857830: 2.1G · 4294967296: 4.0G · 512: 512 (integer maths, no awk)
UNITS=(B K M G T P)
human() {
  local n=$1 i=0 t
  if (( n < 1024 )); then REPLY=$n; return; fi
  while (( n >= 1048576 && i < 4 )); do n=$(( n / 1024 )); i=$(( i + 1 )); done
  t=$(( (n * 10 + 512) / 1024 ))                       # tenths of the next unit, rounded
  printf -v REPLY '%d.%d%s' $(( t / 10 )) $(( t % 10 )) "${UNITS[i + 1]}"
}
# used_of <used bytes> <total bytes> → "2.1G / 8.0G"
used_of() { local u; human "$1"; u=$REPLY; human "$2"; REPLY="$u / $REPLY"; }

# ─── readings: Linux (/proc) or macOS ───
# CPU % since the previous call (macOS: what ps reports, per core like Activity Monitor)
cpu_sample() {
  if (( LINUX )); then
    read -r _ u n s i w q sq _ < /proc/stat; total=$((u+n+s+i+w+q+sq)); idle=$((i+w))
    dt=$(( total - ${prev_total:-0} )); cpu=0
    (( dt > 0 && ${prev_total:-0} > 0 )) && cpu=$(( 100 * (dt - (idle - prev_idle)) / dt ))
    prev_total=$total prev_idle=$idle
  else
    cpu=$(LC_ALL=C ps -A -o %cpu= | awk -v n="$CORES" '{ s += $1 } END { c = s / n; if (c > 100) c = 100; printf "%d", c }')
  fi
}
# memory and swap in KiB: mt total, ma available, st swap total, sf swap free
mem_read() {
  if (( LINUX )); then
    while read -r k v _; do case $k in
      MemTotal:) mt=$v;; MemAvailable:) ma=$v;; SwapTotal:) st=$v;; SwapFree:) sf=$v;; esac; done < /proc/meminfo
  else                         # used = app + wired + compressed, like Activity Monitor
    mt=$(( $(sysctl -n hw.memsize) / 1024 ))
    ma=$(( mt - $(vm_stat | awk '/page size of/ { size = $8 } /Anonymous pages/ { app = $3 }
      /Pages purgeable/ { purge = $3 } /Pages wired down/ { wired = $4 } /occupied by compressor/ { comp = $5 }
      END { printf "%d", (app - purge + wired + comp) * size / 1024 }') ))
    # "total = 2048.00M  used = 1081.25M  free = 966.75M  (encrypted)"
    read -r st sf < <(sysctl -n vm.swapusage | awk 'function kb(v) { m = (v ~ /G/) ? 1048576 : 1024; return int(v * m) }
      { print kb($3), kb($9) }')
  fi
}
# up (seconds since boot), l1 l5 l15 (load)
uptime_read() {
  if (( LINUX )); then
    read -r up _ < /proc/uptime; up=${up%.*}
    read -r l1 l5 l15 _ < /proc/loadavg
  else
    # "{ sec = 1793170000, usec = 123456 } Wed Oct 29 …": the first number (not usec's)
    up=$(( $(date +%s) - $(sysctl -n kern.boottime | sed 's/^{ sec = \([0-9]*\).*/\1/') ))
    read -r _ l1 l5 l15 _ < <(sysctl -n vm.loadavg)            # "{ 1.23 1.10 1.05 }"
  fi
}
# rx tx: bytes received / sent by $IFACE so far
net_read() {
  rx='' tx=''
  if (( LINUX )); then
    local name r t
    while read -r name r _ _ _ _ _ _ _ t _; do
      [[ $name == "$IFACE:" ]] && { rx=$r tx=$t; break; }
    done < /proc/net/dev
  else                         # the <Link#> row; counted from the end (Address may be empty)
    read -r rx tx < <(netstat -ibn | awk -v i="$IFACE" '$1 == i && $3 ~ /^<Link/ { print $(NF-4), $(NF-1); exit }')
  fi
  rx=${rx:-0} tx=${tx:-0}
}
now_ms() {
  if [[ -n $EPOCHREALTIME ]]; then REPLY=${EPOCHREALTIME/[.,]/}; REPLY=$(( REPLY / 1000 ))   # bash ≥ 5: no process
  elif (( LINUX )); then REPLY=$(( $(date +%s%N) / 1000000 ))
  else REPLY=$(perl -MTime::HiRes=time -e 'printf "%.0f\n", time * 1000'); fi
}
# "size used mountpoint" lines, in bytes: the system disk (and Windows' C: in WSL)
disks() {
  if (( LINUX )); then df -kP / /mnt/c 2>/dev/null; else df -kP /System/Volumes/Data 2>/dev/null; fi |
    awk 'NR > 1 { print $2 * 1024, $3 * 1024, $NF }'
}
disk_label() {
  case $1 in /mnt/c) REPLY="C:" ;; /) (( IS_WSL )) && REPLY="WSL" || REPLY="Disk" ;; *) REPLY="Disk" ;; esac
}
my_ip() {
  if (( LINUX )); then ip -o -4 addr show "$IFACE" 2>/dev/null | awk '{print $4; exit}'
  else ipconfig getifaddr "$IFACE" 2>/dev/null; fi
}

# bar <percent> <width>
bar() {
  local p=$1 w=$2 fill col full="" empty="" n
  fill=$(( p * w / 100 )); (( fill > w )) && fill=$w
  col=$C_OK; (( p >= 70 )) && col=$C_WARN; (( p >= 90 )) && col=$C_BAD
  for (( n = 0; n < fill; n++ )); do full+="█"; done
  for (( n = fill; n < w; n++ )); do empty+="░"; done
  REPLY="$col$full$C_TRACK$empty$X"
}

# line <label> <percent> <text>  → one more entry in $out; the bar takes what the text
# leaves, so the line always fits the pane (a wrapped line would push the header away)
line() {
  local text=$3
  (( cols - 16 - ${#text} < 6 )) && text=""          # no room for "used / total": bar and % only
  local w=$(( cols - 16 - ${#text} )) l; (( w > 60 )) && w=60; (( w < 6 )) && w=6
  bar "$2" "$w"
  printf -v l ' %s%-6s%s %s %s%3d%%%s %s%s%s' "$C_TEXT" "$1" "$X" "$REPLY" "$C_TEXT" "$2" "$X" "$C_DIM" "$text" "$X"
  out+=("$l")
}

# spark <width> <values…> → the last <width> values as ▁▂▃…█ scaled to their maximum
spark() {
  local w=$1; shift
  local -a v=("$@"); local n=${#v[@]} max=1 s="" i
  (( n > w )) && v=("${v[@]:$(( n - w ))}")
  for i in "${v[@]}"; do (( i > max )) && max=$i; done
  for i in "${v[@]}"; do s+=${SPARK[ i * 7 / max ]}; done
  REPLY=$s
}

# top-right "󰊓 zoom" / "󰊔 restore": tmux turns a click there into resize-pane -Z (~/.tmux.conf)
zoom_button() {
  if [[ $zoomed == 1 ]]; then printf '\e[1;%dH\e[48;2;137;180;250m\e[38;2;17;17;27m\e[1m 󰊔 restore \e[0m' $(( cols - 10 ))
  else printf '\e[1;%dH\e[48;2;49;50;68m\e[38;2;166;173;200m 󰊓 zoom \e[0m' $(( cols - 7 ))
  fi
}

rate() { human "$1"; [[ $REPLY == *[0-9] ]] && REPLY+="B"; REPLY="${REPLY:-0B}/s"; }

cpu_sample
net_read; prev_rx=$rx prev_tx=$tx
now_ms; prev_t=$REPLY
down=() upl=()
# cursor hidden, and no autowrap: a line too long for the pane is cut instead of
# wrapping onto the next row (which would push the header out of the pane)
# (INT / TERM only exit: the EXIT trap then cleans up, once)
printf '\e[?25l\e[?7l'; trap 'printf "\e[?25h\e[?7h"; [[ -n $TMUX_PANE ]] && tmux set -pu -t "$TMUX_PANE" @wake 2>/dev/null' EXIT
trap 'exit' INT TERM
trap ':' WINCH                 # a resize (zoom / restore) redraws right away
trap ':' USR1                  # back in sight (tmux.conf hooks): look again right away
[[ -n $TMUX_PANE ]] && tmux set -p -t "$TMUX_PANE" @wake $$
# size, zoom and sight in one tmux call · in sight: someone is attached, this is the current
# tab and no other pane of it is zoomed
VIEW='#{pane_width} #{pane_height} #{window_zoomed_flag} #{&&:#{&&:#{window_active},#{session_attached}},#{||:#{?window_zoomed_flag,0,1},#{pane_active}}}'
first=1 round=0
while :; do
  cols='' rows='' zoomed=0 visible=1
  [[ -n $TMUX_PANE ]] && read -r cols rows zoomed visible < <(tmux display -p -t "$TMUX_PANE" "$VIEW" 2>/dev/null)
  if [[ $visible == 0 ]]; then
    sleep 10 & wait $!; kill $! 2>/dev/null     # out of sight: a look every 10 s, or SIGUSR1
    continue
  fi
  [[ -z $cols ]] && { cols=$(tput cols 2>/dev/null || echo 60); rows=$(tput lines 2>/dev/null || echo 9); }
  out=()
  # what rarely changes, every 30 s: the interface (Wi-Fi, VPN…), its IP, the disks
  if (( round % 15 == 0 )); then
    now_if=$(iface)
    if [[ $now_if != "$IFACE" ]]; then IFACE=$now_if; net_read; prev_rx=$rx prev_tx=$tx; fi
    ip=$(my_ip); disk_lines=$(disks)
  fi
  round=$(( round + 1 ))
  # CPU, memory, uptime, load
  cpu_sample
  mem_read
  uptime_read
  # network speed since the last round
  net_read
  now_ms; now=$REPLY; ms=$(( now - prev_t )); (( ms < 1 )) && ms=1
  drate=$(( (rx - prev_rx) * 1000 / ms )) urate=$(( (tx - prev_tx) * 1000 / ms ))
  (( drate < 0 )) && drate=0; (( urate < 0 )) && urate=0
  prev_rx=$rx prev_tx=$tx prev_t=$now
  down+=("$drate"); upl+=("$urate"); (( ${#down[@]} > 120 )) && down=("${down[@]:1}") upl=("${upl[@]:1}")

  if (( cols >= 75 )); then       # leave room for the zoom button on the right
    printf -v head ' %s%s󰍛 %s%s  %sup %dd %dh %dm · load %s %s %s · %d CPU%s' "$B" "$C_HEAD" "$HOST" "$X" \
      "$C_DIM" $((up/86400)) $((up%86400/3600)) $((up%3600/60)) "$l1" "$l5" "$l15" "$CORES" "$X"
  elif (( cols >= 50 )); then
    printf -v head ' %s%s󰍛 %s%s  %sup %dd %dh · load %s%s' "$B" "$C_HEAD" "$HOST" "$X" \
      "$C_DIM" $((up/86400)) $((up%86400/3600)) "$l1" "$X"
  else                            # narrow: the host only (the zoom button needs the rest)
    printf -v head ' %s%s󰍛 %s%s' "$B" "$C_HEAD" "$HOST" "$X"
  fi
  out+=("$head")
  (( first )) && cpu=0
  line "CPU" "$cpu" ""
  used_of $(( (mt - ma) * 1024 )) $(( mt * 1024 )); line "RAM" $(( (mt - ma) * 100 / mt )) "$REPLY"
  if (( st > 0 )); then used_of $(( (st - sf) * 1024 )) $(( st * 1024 )); line "Swap" $(( (st - sf) * 100 / st )) "$REPLY"; fi
  # the GPU and the ping every third round (6 s): nvidia-smi takes 30-55 ms on WSL, the ping waits
  # on the network · the last answer is shown in between (read takes the first line: no head)
  if [[ -n $NVSMI ]] && (( round % 3 == 1 )); then
    gpu_raw=""; read -r gpu_raw < <("$NVSMI" --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits 2>/dev/null)
  fi
  if [[ -n ${gpu_raw:-} ]] && IFS=', ' read -r gu gm gt gtemp gpow <<< "$gpu_raw" && [[ $gu =~ ^[0-9]+$ && $gm =~ ^[0-9]+$ && $gt =~ ^[0-9]+$ ]]; then     # [N/A] (no memory data): no GPU line
    [[ $gtemp =~ ^[0-9.]+$ ]] || gtemp=""; [[ $gpow =~ ^[0-9.]+$ ]] || gpow=""
    used_of $(( gm * 1048576 )) $(( gt * 1048576 )); gpu_txt=$REPLY
    (( cols >= 50 )) && [[ -n $gtemp ]] && gpu_txt+=" · ${gtemp%.*}°C"
    (( cols >= 60 )) && [[ -n $gpow ]] && gpu_txt+=" · ${gpow%.*}W"
    line "GPU" "$gu" "$gpu_txt"
  fi
  while read -r size used mnt; do
    [[ -z $size || $size == 0 ]] && continue
    disk_label "$mnt"; label=$REPLY
    used_of "$used" "$size"; line "$label" $(( used * 100 / size )) "$REPLY"
  done <<< "$disk_lines"
  # Net: ↓ speed + history · ↑ speed + history (history width fits the pane)
  sw=$(( (cols - 36) / 2 )); (( sw < 4 )) && sw=4; (( sw > 40 )) && sw=40
  rate "$drate"; dtxt=$REPLY; spark "$sw" "${down[@]}"; dspark=$REPLY
  rate "$urate"; utxt=$REPLY; spark "$sw" "${upl[@]}"; uspark=$REPLY
  printf -v net ' %s%-6s%s %s↓ %-9s%s%s  %s↑ %-9s%s%s' "$C_TEXT" "Net" "$X" \
    "$C_DOWN" "$dtxt" "$dspark" "$X" "$C_UP" "$utxt" "$uspark" "$X"
  out+=("$net")
  # Web: are we online, and how far is the internet
  if (( round % 3 == 1 )); then           # (ping itself in the $(…): one fork, not a function's two)
    if (( LINUX )); then ping_out=$(ping -c1 -W1 -n 1.1.1.1 2>/dev/null) || ping_out=""
    else ping_out=$(ping -c1 -t1 -n 1.1.1.1 2>/dev/null) || ping_out=""; fi
  fi
  if [[ $ping_out =~ time[=\<]([0-9]+) ]]; then
    lat=${BASH_REMATCH[1]}
    lc=$C_OK; (( lat >= 100 )) && lc=$C_WARN; (( lat >= 300 )) && lc=$C_BAD
    # as much as fits: a wrapped line would push the header out of the pane
    if   (( cols >= 70 )); then tail_txt=" to 1.1.1.1 · $IFACE $ip"
    elif (( cols >= 50 )); then tail_txt=" to 1.1.1.1"
    else                        tail_txt=""
    fi
    printf -v web '%s● online%s %s· %s%s ms%s %s%s' "$C_OK" "$X" "$C_DIM" "$lc" "$lat" "$X" "$C_DIM" "$tail_txt"
  else
    if (( cols >= 70 )); then tail_txt=" · no answer from 1.1.1.1 · $IFACE ${ip:-no IP}"; else tail_txt=" · no answer"; fi
    printf -v web '%s● offline%s %s%s' "$C_BAD" "$X" "$C_DIM" "$tail_txt"
  fi
  printf -v web ' %s%-6s%s %s%s' "$C_TEXT" "Web" "$X" "$web" "$X"
  out+=("$web")

  # never more lines than the pane has (a trailing newline would scroll the header away)
  printf '\e[H'
  for (( n = 0; n < ${#out[@]} && n < rows; n++ )); do
    (( n )) && printf '\n'
    printf '%s\e[K' "${out[n]}"
  done
  printf '\e[J'
  zoom_button
  # the pane as tall as what it shows (swap, a GPU, how many disks: it depends on the machine,
  # system.sh only guesses): noted in @rows, which info-fit.sh keeps on resizes · only when the
  # number changes, and never while zoomed (a resize would undo the zoom)
  if [[ -n $TMUX_PANE && $zoomed == 0 && ${#out[@]} != "${fit_rows:-}" ]]; then
    fit_rows=${#out[@]}
    tmux set -p -t "$TMUX_PANE" @rows "$fit_rows" \; resize-pane -t "$TMUX_PANE" -y "$fit_rows" 2>/dev/null
  fi
  first=0
  sleep 2 & wait $!; kill $! 2>/dev/null
done
