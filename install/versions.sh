# shellcheck shell=bash disable=SC2034  # its variables are read by the scripts that source it
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

# sha256 of each download, checked before it is used (install/lib.sh: download): a changed or
# broken file installs nothing. A version above changes → its sums here too: from the release's
# checksums file (fzf, lazygit, yq, nerd-fonts publish one) or `sha256sum` of the download.
SHA_fzf_amd64=4be08018ca37b32518c608741933ea335a406de3558242b60619e98f25be2be1
SHA_fzf_arm64=7071f48c2ac0f2bc992d6d33cc36fd675a579a98cc976dda699eea07dd5e9c58
SHA_fastfetch_amd64=3f3961d5a3152ffd8a373776e6a34ed739ca0e83c662853e197ca90fa2db9905
SHA_fastfetch_arm64=9b5733b8a49aba9d3ca6218ec9a882ff79e414f6daaf822d0dcc66d0a4e27af2
SHA_lazygit_amd64=158efc9ddfa1241fab5fb3526bb442c8dc6c4b1904d73213b9e4e93e03c52034
SHA_lazygit_arm64=79a3161eeb642f0473e23db6341f7baabd4a5933e921a9c1167c5d5c765c41a4
SHA_yq_amd64=8e34fc298390875de416e6a4afcb8cabeceb25d9aa8506c1a2f9353cf702ea5f
SHA_yq_arm64=189088da0c6429ec5178dfaab1a114805f6cab0b61b165ab236efedf1d57a71b
SHA_tmux=b6d8d9c76585db8ef5fa00d4931902fa4b8cbe8166f528f44fc403961a3f3759
SHA_font=fab782a66f7d3019da64f6572db9fc5d3a4bcb19f9fa13e2d8a62e3693d6396e
