#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════════
#  tmux guide · every shortcut in one list
#  Opened with Ctrl+a ? (or Ctrl+a g) inside tmux, or `terminal guide`.
#  Shown by tmux/guide.py: hover highlights · click or Enter runs ·
#  wheel scrolls · type to search · Esc closes.
#
#  This file is the single source of truth for the shortcuts cheat sheet.
#  Entry format:  keys | Description | tmux command to run on click / Enter (optional)
#                 keys in [ ] are drawn as keys: [Ctrl+a] [Space]; the rest as plain text
#  Tabs:          @@Title | subtitle      Groups: @Title | subtitle
#  Special commands: @picker (session picker), @shell:<cmd> (run in this popup),
#                    @keys:<k> (replay Ctrl+a <k>)
# ═══════════════════════════════════════════════════════════════

emulate -L zsh
export TERMINAL_SETUP=${0:A:h:h}            # the repo (this file is in its tmux/)

B=$'\e[1m' D=$'\e[2m' C=$'\e[36m' G=$'\e[32m' Y=$'\e[33m' M=$'\e[35m' X=$'\e[0m'
TAB=$'\t'

GUIDE=$(cat <<'EOF'
@@Shortcuts|press Ctrl+a, let go, then the key
@Everyday|the ones you will use most
[Ctrl+a] [Space]|Quick menu with the most used actions|@menu
[Ctrl+a] [?]  or  [Ctrl+a] [g]|This guide|
[Ctrl+a] [s]|Switch session · hover previews it, right-click for more|@picker
[Ctrl+a] [c]|New tab in this folder|new-window -c "#{pane_current_path}"
[Ctrl+a] [v]|Split side by side|split-window -h -c "#{pane_current_path}"
[Ctrl+a] [-]|Split below|split-window -v -c "#{pane_current_path}"
[Ctrl+a] [z]|Zoom the pane in / out|resize-pane -Z
[Ctrl+a] [x]|Close the pane · asks if a program is still running in it, or it is the last one of the session|@keys:x
[Ctrl+a] [d]|Detach · leave tmux, everything keeps running|detach-client
@Tabs|the windows in the top bar
[Shift+←] / [Shift+→]|Previous / next tab · micro and vim keep them for selecting|
[Ctrl+a] [1…9]|Go to tab N|
[Ctrl+a] [Tab]|Back to the last tab|last-window
[Ctrl+a] [,]|Rename the tab|command-prompt -I "#W" -p "Tab name:" { rename-window "%%" }
[Ctrl+a] [C]|New tab with a name|command-prompt -p "Tab name:" { new-window -n "%%" -c "#{pane_current_path}" }
[Ctrl+a] [<] / [>]|Move the tab left / right · keep tapping|
[Ctrl+a] [&]|Close the tab · asks first|@keys:&
@Panes|splits inside a tab
[Ctrl+a] [h] [j] [k] [l]|Go to the pane left / down / up / right|
[Ctrl+a] [←] [↑] [→] [↓]|Same with the arrows · keep tapping to keep moving|
[Ctrl+a] [H] [J] [K] [L]|Resize the pane · keep tapping to repeat|
[Ctrl+a] [b]|Move the pane to its own tab|break-pane
[Ctrl+a] [m]|Bring another tab in as a pane|command-prompt -p "Join tab number:" { join-pane -h -s ":%%" }
[Ctrl+a] [a]|Type in all panes at once · on / off|setw synchronize-panes
[Ctrl+a] [Space] [l]|Next layout|next-layout
[Ctrl+a] [Space] [>]|Swap with the next pane|swap-pane -D
click here|Even out the pane sizes|select-layout -E
click here|Swap with the previous pane|swap-pane -U
@Sessions|workspaces that keep running in the background
[Ctrl+a] [N]|New session in this folder|command-prompt -p "New session name:" { new-session -s "%%" -c "#{pane_current_path}" }
[Ctrl+a] [$]|Rename the session · the system monitor keeps its name|@keys:'$'
[Ctrl+a] [Shift+Tab]|Back to the last session|switch-client -l
[Ctrl+a] [S]|Session tree · every session and tab, with a live preview|@keys:S
[Ctrl+a] [X]|Close the session · asks first, then pick another|@keys:X
@Copy, extract & links|everything you copy goes to the Windows clipboard
[Ctrl+a] [y]  or  [Ctrl+a] [Esc]|Scroll and copy with the keyboard|copy-mode
[Ctrl+V]|Paste · Windows Terminal|
[Ctrl+a] [e]|Extract · pick any word, path, id or line on screen|@keys:e
[Ctrl+a] [u]|Links · list the URLs on screen and open one in the browser|@keys:u
[Ctrl+a] [G]|lazygit for the folder of this pane · q closes it|@keys:G
@Inside copy mode|after Ctrl+a y, or once you scroll with the wheel
[↑] [↓] [PgUp] [PgDn]|Scroll|
[g] / [G]|Top / bottom of the history|
[v] · [r] · [y]|Select · block select · copy|
[/] · [n] · [N]|Search · next · previous match|
[q]  or  [Esc]|Leave · Esc first clears a selection|
@Inside popups|session picker, extract, links, this guide
[Enter]|Open · insert · open the link|
[Ctrl+n] · [Ctrl+r] · [Ctrl+e] · [Ctrl+x] · [Ctrl+t]|Session picker · new · rename · describe · close (asks first) · tree|
[Ctrl+s] in the session picker|New terminals open this session · again: back to the system monitor|
[y] / [n]  or  [Esc]|A question (close, kill, clear…) · or click its answer|
[Ctrl+y]|Extract and links · copy instead|
[Ctrl+f] · [Ctrl+g]|Extract · word / path / url / line · this pane or the whole tab|
[Tab]|Links · mark several · Guide · next tab of the guide|
[Esc]|Clear the search, then close|
@Save & settings|sessions are saved every 5 min and restored when tmux starts
[Ctrl+a] [Ctrl+s]|Save the sessions now|run-shell ~/.tmux/plugins/tmux-resurrect/scripts/save.sh
[Ctrl+a] [Ctrl+r]|Restore the last save|run-shell ~/.tmux/plugins/tmux-resurrect/scripts/restore.sh
[Ctrl+a] [r]|Reload ~/.tmux.conf · also happens by itself when you save it|source-file ~/.tmux.conf ; display-message "config reloaded"
[Ctrl+a] [I]|Install plugins|run-shell ~/.tmux/plugins/tpm/bindings/install_plugins
[Ctrl+a] [U]|Update plugins|run-shell ~/.tmux/plugins/tpm/bindings/update_plugins
[Ctrl+a] [/]|What does a key do? · press it to find out|command-prompt -k -p key { list-keys -1N "%%" }
[Ctrl+a] [Ctrl+a]|Send Ctrl+a to the program · start of line in the shell|
@System monitor|the system session · 1 info · 2 monitor (processes, ports) · 3 disk · 4 packages · 5 ssh · 6 docker · 7 git
[Ctrl+a] [M]|Go to the system monitor · or click CPU / RAM on the bar|@keys:M
[Right-click] a container|Logs · shell as you or root · open its port · start, restart, stop, pause, kill, remove · compose project (ask first)|
[Double-click] a port in Containers or Ports|Open http://localhost:PORT in the browser|
highlight a container|Its details, Dockerfile, compose file and live logs appear next to it|
[Right-click] a package|Why I installed it (note) · details · uninstall (asks first) · apt, snap and brew|
type in Search|Find any apt, snap or brew package · right-click to install it (asks first)|
[Right-click] an update|Upgrade it or everything from its source (ask first) · check for updates|
[Click] all · apt · snap · brew|Show the packages of one source only (on the Packages, Updates and Search titles)|
[Right-click] a process|Stop · force kill (both ask first) · show its ports · copy PID or command|
[Double-click] a folder in Folders|Go into it · .. or [Backspace] goes up · a file opens with the system's app|
[Right-click] a folder|Open · open with the system's app · terminal session here · measure again · delete (asks first)|
[Right-click] in Cleanup|Clean it (asks first, says how much) · show its folder · run clean|
[Double-click] a disk|Show its folders (in Folders)|
[Double-click] a host|Connect in a session of its own (ssh-NAME) · a git host: which account sees your key|
[Right-click] a host|Connect in a popup · test the login · open / close a tunnel · install your key · edit ~/.ssh/config · add a host|
[Right-click] a key|Copy the public key · add to / remove from the agent · create a new key|
[Double-click] a repo|Open it in a session of its own|
[Right-click] a repo|Fetch · pull (fast-forward only) · push (asks first) · fetch every repo · lazygit · open its page · folders to look in|
[Right-click] a port|Open in the browser · copy · stop its program (asks first) · show the process or container|
[Del]|Stop the highlighted process or port program · asks first|
[↑] [↓] [PgUp] [PgDn] [Home] [End]|Move in a list · the panes next to it follow the highlighted row|
[Enter] on a row|Its menu (the same as right-click) · ↑↓ and Enter, or the letter in ( ) · Esc closes|
[←] / [→] in a list|Sort by the previous / next column · [Ctrl+r] reverses the order|
click a column title|Sort by it · again: reverse · a third time: the order the list started with|
[Tab] / [Shift+Tab] in a package list|Next / previous source · all · apt · snap · brew (or click them)|
[Double-click] a row|Its main action: open the port in the browser · elsewhere its menu|
[Wheel] on a long menu|Scroll it · ▲ ▼ on its border show there is more|
type|Filter the list · Esc or a click on ✕ clears it|
[Tab] / [←] [→] in details, Logs, Package, Host, Repo|Next / previous tab (or click it)|
[Enter] in details, Logs, Package, Host, Repo|Its menu · copy, select text, save, time range, zoom|
[Ctrl+a] [X] in system|Restart the monitor (it is always there) · a pane or tab you close comes back by itself|
[Click] 󰊓 zoom on a pane title|Zoom that pane · 󰊔 restore (or double-click the title)|
[Double-click] btop, fastfetch, Resources|Zoom it · again to restore|
[Click] ZOOM · restore (top bar)|Restore a zoomed pane, from anywhere|
[Drag] in Logs or details|Select lines · releasing copies them (Logs: the original lines, e.g. whole JSON)|
[Right-click] → Select text freely|Any text, only in that pane (tmux copy mode) · drag, release copies · q leaves|
[Right-click] in Logs|Save the lines shown / the whole log (asks where) · time range: 15 min… everything|
@Tools|logging, stuck programs, docker
[Ctrl+a] [P]|Start / stop logging this pane to ~/.tmux/logs · shows ● REC|run-shell ~/.tmux/plugins/tmux-logging/scripts/toggle_logging.sh
[Ctrl+a] [Alt+p]|Save what is on screen to ~/.tmux/logs|run-shell ~/.tmux/plugins/tmux-logging/scripts/screen_capture.sh
[Ctrl+a] [Alt+Shift+p]|Save the whole history to ~/.tmux/logs|run-shell ~/.tmux/plugins/tmux-logging/scripts/save_complete_history.sh
[Ctrl+a] [Alt+c]|Clear the pane history · says how many lines and asks first|@keys:M-c
[Ctrl+a] [*]|Kill the stuck program in this pane · kill -9, asks first|@keys:*
[Ctrl+a] [Space] [D]|Docker compose logs in a pane below|split-window -v -l 30% -c "#{pane_current_path}" "docker compose logs -f --tail=100 || sleep 5"
@@Mouse|everything can also be done with the mouse
@Top bar|tabs, session and buttons
[Click] a tab|Go to that tab|
[Click] [] after the tabs|New tab|new-window -c "#{pane_current_path}"
[Double-click] empty bar|New tab|new-window -c "#{pane_current_path}"
[Middle-click] a tab|Close it · asks first|
[Right-click] a tab|Tab menu · rename, move, split, close (asks first)|
[Wheel] on the bar|Previous / next tab|
[Click] CPU / RAM|Go to the system monitor|@keys:M
[Click] [◀] / [▶]|Previous / next tab · shown when they do not all fit (the system monitor's keep their whole names)|
[Click] the session|Switch session|@picker
[Right-click] the session|Session menu · switch, new, rename, detach, close|
[Click] [󰍜]|Quick menu|@menu
[Click] [󰋖]|This guide|
[Right-click] empty bar|Quick menu|@menu
@Panes|inside a tab
[Click]|Focus the pane|
[Drag] a border|Resize the panes|
[Wheel]|Scroll back · shows ↑ lines and % on the pane label|
[Drag]|Select and copy · a plain click copies nothing|
[Double-click]|Copy a word, path or URL|
[Triple-click]|Copy the whole line|
[Right-click]|Pane menu · copy, paste, extract, links, logging, split, zoom, close|
[Alt+Right-click]|Pane menu inside apps that use the mouse (micro, htop)|
[Shift+Drag]|Windows Terminal's own selection · it spans every pane on screen: zoom first, or use Select text freely|
@Menus & popups|quick menu, this guide, session picker
[Hover]|Highlights · in the session picker it previews the session|
[Click]|Runs it or opens it|
[Right-click] a session|Open, rename, describe, new terminals start here, new, session tree, close · close asks first (system: restart)|
[Wheel]|Scrolls the list|
[Click] outside|Closes the menu|
[Click] an answer|Questions (close a tab, kill a program, clear the history…) · or press y / n · Esc cancels|
@@Terminal|commands for any shell, also outside tmux
@Sessions|the terminal command
terminal|Session picker|@picker
terminal system|System monitor · new terminals open it (unless terminal start chose another)|@keys:M
terminal system restart|Rebuild the system monitor|run-shell -b "$TERMINAL_SETUP/tmux/system.sh restart"
terminal open api ~/dir|Open a session, or create it in that folder (default: here)|
terminal list|List the sessions|@shell:$TERMINAL_SETUP/tmux/terminal.zsh list; read -sk "?press any key"
terminal rename old new|Rename a session|
terminal kill name|Close a session · asks first (system: restarts it)|
terminal kill-all|Close every session but the system monitor · asks first, and saves so they stay closed|
terminal start name|New terminals open that session (created in its folder if closed) · terminal start system: the monitor|@shell:$TERMINAL_SETUP/tmux/terminal.zsh start; read -sk "?press any key"
terminal guide|This guide|
terminal files|Every file the install put on this machine, and what it is for|@shell:bash $TERMINAL_SETUP/install/files.sh | less -R
terminal help|Every command|@shell:$TERMINAL_SETUP/tmux/terminal.zsh help; read -sk "?press any key"
@Shell|functions and aliases of zsh/functions.zsh and zsh/aliases.zsh
update|Update everything: apt, snap, brew, uv, pnpm, Composer, Node LTS (fnm), tldr pages, plugins|
clean|Clean caches: apt, journal, snap, brew, Docker build cache, uv, pnpm, npm, Composer|
rgf text|Search inside files (rg), pick a match with its preview, open the editor on that line|
fe pattern|Pick files by name (fd · Tab marks several) and open them in the editor|
z part · zi|Jump to a folder you use often (zoxide) · zi: pick it from a list|
lg|lazygit · git in the terminal|
tldr cmd|Short examples of any command (tldr tar)|
mkcd dir|Create a folder and go into it|
extract file|Unpack any archive (tar.*, zip, 7z, rar, gz…)|
serve 8000|Web server for this folder · PHP when there is an index.php, Python otherwise|
ports · killport 3000|What listens on each port · free one (asks first)|
dps · dsh|Docker containers at a glance · open a shell in one|
fkill|Pick processes with fzf and stop them|
installed-packages|The packages you installed yourself, and why|
pn · uvr|pnpm · uv run|
@Settings|in your ~/.zshrc, above the terminal-setup line
export TERMINAL_NO_AUTOSTART=1|Do not open tmux in new tabs|
EOF
)

# Render: section headers in yellow, keys in cyan, section tag (dim, searchable) on the right
render() {
  local keys desc cmd section
  while IFS='|' read -r keys desc cmd; do
    if [[ $keys == @@* ]]; then
      print -r -- "${TAB}${B}${M}${(U)keys#@@}${X}  ${D}${desc}${X}"
    elif [[ $keys == @* ]]; then
      section=${${keys#@}:l}
      print -r -- "${TAB}${B}${Y}${keys#@}${X}  ${D}${desc}${X}"
    else
      keys=${${keys//\[/}//\]/}
      print -r -- "${cmd}${TAB}  $(printf "${C}%-30s${X}" "$keys") $(printf "%-62s" "$desc") ${D}${section}${X}"
    fi
  done <<< "$GUIDE"
}

# ─────────────── Viewer ───────────────
# tmux/guide.py shows every entry in one list: hover, click to run, wheel
# scrolls, type to search. The fzf search below is only the fallback without python3.
[[ $1 != search ]] && (( $+commands[python3] )) && exec python3 -I $TERMINAL_SETUP/tmux/guide.py


# ─────────────── Search (fzf) ───────────────

run() {
  local cmd=$1
  [[ -z $cmd ]] && return
  if [[ -z $TMUX ]]; then
    print -r -- "${D}Open tmux (${X}${C}terminal${X}${D}) to run actions from the guide.${X}"; return
  fi
  case $cmd in
    @picker)  exec $TERMINAL_SETUP/tmux/terminal.zsh pick ;;
    @shell:*) eval "${cmd#@shell:}" ;;
    @menu)    # replay Ctrl+a Space on this client once the popup is gone
              tmux run-shell -b -d 0.1 -C "send-keys -K -c '$(tmux display -p '#{client_name}')' C-a Space" ;;
    @keys:*)  # replay Ctrl+a <key> (for bindings defined by plugins)
              tmux run-shell -b -d 0.1 -C "send-keys -K -c '$(tmux display -p '#{client_name}')' C-a ${cmd#@keys:}" ;;
    *)        # run after the popup closes so prompts and splits land in the real pane
              tmux run-shell -b -d 0.1 -C "$cmd" ;;
  esac
}

if ! (( $+commands[fzf] )); then
  render | cut -f2- | less -R
  exit
fi

query=; [[ $1 == search ]] && query=$2

# The wheel scrolls the list 3 lines at a time (like a page) instead of moving
# the cursor one entry; click selects, double-click runs.
line=$(render | fzf --ansi --delimiter=$TAB --with-nth=2.. --height=100% \
         --layout=reverse --tiebreak=index --border=none --info=inline-right \
         --prompt="search ❯ " --pointer="▶" --gutter=" " --scrollbar="▐" \
         --bind="scroll-up:offset-up+offset-up+offset-up,scroll-down:offset-down+offset-down+offset-down" \
         --query="$query" \
         --header="type to search · enter or double-click runs it · wheel scrolls · esc closes" \
         --color="header:dim,scrollbar:#89b4fa")
run "${line%%$TAB*}"
