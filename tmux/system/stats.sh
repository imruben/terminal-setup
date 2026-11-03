#!/usr/bin/env bash
# CPU and RAM for the tmux status bar (#(…), every status-interval seconds).
# Linux: CPU is the average since the previous call (/proc/stat, kept in a small cache
# file), RAM used = total - available. macOS: CPU from ps (summed per core, the way
# Activity Monitor adds it up), RAM used = app + wired + compressed memory (vm_stat).
colour() { if (( $1 >= 90 )); then echo '#f38ba8'; elif (( $1 >= 70 )); then echo '#f9e2af'; else echo '#a6adc8'; fi; }

if [[ -r /proc/stat ]]; then
  cache=${XDG_RUNTIME_DIR:-/tmp}/tmux-cpu-$UID
  read -r _ u n s i w q sq _ < /proc/stat; total=$((u+n+s+i+w+q+sq)); idle=$((i+w))
  cpu=0
  if [[ -r $cache ]] && read -r pt pi < "$cache" && (( total > pt )); then
    cpu=$(( 100 * ((total - pt) - (idle - pi)) / (total - pt) ))
  fi
  echo "$total $idle" > "$cache"
  while read -r k v _; do case $k in MemTotal:) mt=$v;; MemAvailable:) ma=$v;; esac; done < /proc/meminfo
  used_kb=$(( mt - ma ))
else                                                   # macOS
  cores=$(sysctl -n hw.ncpu)
  cpu=$(LC_ALL=C ps -A -o %cpu= | awk -v n="$cores" '{ s += $1 } END { c = s / n; if (c > 100) c = 100; printf "%d", c }')
  mt=$(( $(sysctl -n hw.memsize) / 1024 ))
  used_kb=$(vm_stat | awk '
    /page size of/            { size = $8 }
    /Anonymous pages/         { app = $3 }
    /Pages purgeable/         { purge = $3 }
    /Pages wired down/        { wired = $4 }
    /occupied by compressor/  { comp = $5 }
    END { printf "%d", (app - purge + wired + comp) * size / 1024 }')
fi
mem=$(( used_kb * 100 / mt ))
used=$(awk -v k="$used_kb" 'BEGIN { printf "%.1fG", k/1048576 }')
printf '#[fg=%s]󰍛 %d%%  #[fg=%s]󰘚 %s' "$(colour "$cpu")" "$cpu" "$(colour "$mem")" "$used"
