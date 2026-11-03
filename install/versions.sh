# ═══════════════════════════════════════════════════════════════
#  terminal-setup · versions of what install.sh fetches itself (when the system's
#  package is missing or too old) and the minimums the setup needs
# ═══════════════════════════════════════════════════════════════

TMUX_MIN=3.6            # the config uses tmux 3.6 options (pane-scrollbars, menus, formats)
TMUX_VERSION=3.6a       # built from source where the system's tmux is older
FZF_MIN=0.48            # `fzf --zsh` (key bindings and completion) appeared in 0.48
FZF_VERSION=0.67.0
FASTFETCH_VERSION=2.57.1
LAZYGIT_VERSION=0.66.2   # Ubuntu 24.04 has no lazygit: official binary
YQ_VERSION=4.54.1        # mikefarah/yq: Ubuntu's yq package is another program
NERD_FONT_VERSION=v3.5.1
NERD_FONT=JetBrainsMono  # the font family the terminal must use: "JetBrainsMono Nerd Font"
PYTHON_MIN=3.8          # the tmux panels (Python, standard library only)
