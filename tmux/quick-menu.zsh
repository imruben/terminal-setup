#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════════
#  Quick menu · Ctrl+a Space, the 󰍜 button, right-click on the bar
#  Opened from this script (not straight from tmux.conf) so tmux can tell it is
#  on screen: @quick-menu holds "<client>:<pid>" while it is open, and the
#  client-resized hook in ~/.tmux.conf closes it and reopens it centred.
# ═══════════════════════════════════════════════════════════════

emulate -L zsh
export TERMINAL_SETUP=${0:A:h:h}            # the repo (this file is in its tmux/)
client=${1:-$(tmux display -p '#{client_name}')}

# 25 rows tall · in a shorter terminal the section titles go (22 rows) · shorter still,
# the guide opens instead
height=$(tmux display -p -c "$client" '#{client_height}')
if (( height < 23 )); then
  tmux set -g @popup-client "$client"
  exec tmux display-popup -c "$client" -E -e TMUX_IN_POPUP=1 -w 80% -h 85% -b rounded -S "fg=#89b4fa" \
    -T "#[align=centre,fg=#89b4fa,bold] tmux guide " "$TERMINAL_SETUP/tmux/guide.zsh"
fi

items=(
  '-#[fg=#6c7086,bold]PANES'                                             '' ''
  '󰡌  Split side by side'                                                'v' 'split-window -h -c "#{pane_current_path}"'
  '󰡋  Split below'                                                       '-' 'split-window -v -c "#{pane_current_path}"'
  '󰊓  #{?window_zoomed_flag,Unzoom,Zoom} pane'                           'z' 'resize-pane -Z'
  '󰕵  Next layout'                                                       'l' 'next-layout'
  '󰓡  Swap with next pane'                                               '>' 'swap-pane -D'
  '󰏌  Move pane to its own tab'                                          'b' 'break-pane'
  '󰓦  #{?pane_synchronized,Stop typing in all panes,Type in all panes}'  'a' 'setw synchronize-panes'
  '󰅖  Close pane'                                                        'x' 'run -C "send-keys -K -c '\''#{client_name}'\'' C-a x"'
  '-#[fg=#6c7086,bold]TABS & SESSIONS'                                   '' ''
  '󰝜  New tab'                                                           'c' 'new-window -c "#{pane_current_path}"'
  '󰏫  Rename tab'                                                        ',' 'command-prompt -I "#W" -p "Tab name:" { rename-window "%%" }'
  '󰉹  Switch session'                                                    's' 'set -gF @popup-client "#{client_name}" ; display-popup -E -e TMUX_IN_POPUP=1 -w 75% -h 70% -b rounded -S "fg=#89b4fa" -d "#{pane_current_path}" -T "#[align=centre,fg=#89b4fa,bold] sessions " "$TERMINAL_SETUP/tmux/terminal.zsh pick"'
  '󰐕  New session'                                                       'N' 'command-prompt -p "New session name:" { new-session -s "%%" -c "#{pane_current_path}" }'
  '󰏫  Rename session'                                                    '$' 'run -C "send-keys -K -c '\''#{client_name}'\'' C-a '\''$'\''"'
  '󰈆  Detach (keeps running)'                                            'd' 'detach-client'
  '-#[fg=#6c7086,bold]TOOLS'                                             '' ''
  '󰍉  Extract text from screen'                                          'e' 'run -C "send-keys -K -c '\''#{client_name}'\'' C-a e"'
  '󰌷  Open a link from screen'                                           'u' 'run -C "send-keys -K -c '\''#{client_name}'\'' C-a u"'
  '  lazygit for this folder'                                           'G' 'run -C "send-keys -K -c '\''#{client_name}'\'' C-a G"'
  '  Docker logs below'                                                 'D' 'split-window -v -l 30% -c "#{pane_current_path}" "docker compose logs -f --tail=100 || sleep 5"'
  '󰆓  Save sessions now'                                                 'C-s' 'run-shell "~/.tmux/plugins/tmux-resurrect/scripts/save.sh"'
  '󰋖  Guide · all shortcuts'                                             '?' 'set -gF @popup-client "#{client_name}" ; display-popup -E -e TMUX_IN_POPUP=1 -w 80% -h 85% -b rounded -S "fg=#89b4fa" -T "#[align=centre,fg=#89b4fa,bold] tmux guide " "$TERMINAL_SETUP/tmux/guide.zsh"'
  '󰑐  Reload config'                                                     'r' 'source-file ~/.tmux.conf ; display-message "config reloaded"'
)

if (( height < 28 )); then
  local -a compact
  for (( i = 1; i <= $#items; i += 3 )); do
    [[ ${items[i]} == -* ]] || compact+=("${(@)items[i,i+2]}")
  done
  items=("${compact[@]}")
fi

token="$client:$$"
tmux set -g @quick-menu "$token"
tmux display-menu -c "$client" -M -O -T "#[align=centre,fg=#89b4fa,bold] quick menu " -x C -y C -- "${items[@]}"
[[ $(tmux show -gqv @quick-menu) == $token ]] && tmux set -gu @quick-menu
