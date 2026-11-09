# shellcheck shell=bash disable=SC2034  # its variables are read by the scripts that source it
# ═══════════════════════════════════════════════════════════════
#  terminal-setup · shared helpers for install.sh and its parts
#  bash 3.2 compatible (macOS's /bin/bash): no associative arrays, no ${x,,}…
# ═══════════════════════════════════════════════════════════════

# tools installed by the setup itself live here too (not always on $PATH yet)
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
case ":$PATH:" in *":/usr/local/bin:"*) ;; *) PATH="/usr/local/bin:$PATH" ;; esac
export PATH

# A repo in a folder with spaces is used through a link without them: tmux, the monitor and the
# plugins run its scripts through sh, which would cut the path at the space. install.sh makes it;
# the scripts that build shell commands go through it (tmux/system.sh, zsh/zshrc, tmux/*.zsh).
REPO_LINK="$HOME/.local/share/terminal-setup"
repo_path() {   # repo_path <repo>: the path your files use for it
  case $1 in *[[:space:]]*) printf '%s' "$REPO_LINK" ;; *) printf '%s' "$1" ;; esac
}

# repo_version <repo>: which version this is, from git (CHANGELOG.md says what each one brought) ·
# v1.0.0 a release · v1.0.0-3-gabc1234 three commits after it · -dirty with changes not committed
# yet · abc1234 no release yet · unknown without git (a downloaded zip)
repo_version() {
  git -C "$1" describe --tags --match 'v[0-9]*' --always --dirty 2>/dev/null || printf 'unknown'
}

# logs of long steps (apt-get, the tmux build), shown only when they fail
LOG_DIR=${XDG_CACHE_HOME:-$HOME/.cache}/terminal-setup

B=$'\e[1m' D=$'\e[2m' R=$'\e[0m' BLUE=$'\e[34m' GREEN=$'\e[32m' YELLOW=$'\e[33m' RED=$'\e[31m'

step()  { printf '\n%s%s==>%s %s%s\n' "$B" "$BLUE" "$R$B" "$*" "$R"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    %s✔%s %s\n' "$GREEN" "$R" "$*"; }
warn()  { printf '    %s!%s %s\n' "$YELLOW" "$R" "$*"; }
fail()  { printf '    %s✘ %s%s\n' "$RED" "$*" "$R" >&2; }
die()   { fail "$*"; exit 1; }

# download <url> <file> <name in versions.sh's SHA_…>: the file, checked against its sha256
# before anything uses it (a download that changed or broke installs nothing)
download() {
  local url=$1 file=$2 var="SHA_$3" want got
  want=${!var:-}
  [ -n "$want" ] || die "no checksum for $3 in install/versions.sh: add its $var"
  run curl -fsSL -o "$file" "$url"
  [ "${DRY_RUN:-0}" = 1 ] && return 0
  if have sha256sum; then got=$(sha256sum "$file"); else got=$(shasum -a 256 "$file"); fi
  got=${got%% *}
  if [ "$got" != "$want" ]; then
    rm -f "$file"
    die "${url##*/}: its checksum is not the expected one (got $got, expected $want): nothing was installed from it"
  fi
}
have()  { command -v "$1" >/dev/null 2>&1; }
# /home/me/x → ~/x for messages
tilde() { case $1 in "$HOME"*) printf '~%s' "${1#"$HOME"}" ;; *) printf '%s' "$1" ;; esac; }

# ask "question" → yes (0) / no (1); --yes answers yes to everything
ask() {
  [ "${ASSUME_YES:-0}" = 1 ] && return 0
  local reply
  printf '    %s%s%s [y/N] ' "$YELLOW" "$1" "$R"
  read -r reply </dev/tty || return 1
  case $reply in [yY]|[yY][eE][sS]|[sS]|[sS][iI]) return 0 ;; *) return 1 ;; esac
}

# run a command, or only show it with --dry-run
run() {
  if [ "${DRY_RUN:-0}" = 1 ]; then
    printf '    %s[dry-run]%s %s\n' "$D" "$R" "$*"
  else
    "$@"
  fi
}

# root runs things as is; anyone else through sudo
as_root() {
  if [ "$(id -u)" = 0 ]; then run "$@"; else run sudo "$@"; fi
}

# version_ge 3.6a 3.6 → true · compares the numeric parts (3.6a → 3 6)
version_ge() {
  local a b i x y
  a=$(printf '%s' "$1" | sed 's/^[^0-9]*//; s/[^0-9.].*//; s/\.$//')     # next-3.7 → 3.7 too
  b=$(printf '%s' "$2" | sed 's/^[^0-9]*//; s/[^0-9.].*//; s/\.$//')
  IFS=. read -r -a x <<< "$a"
  IFS=. read -r -a y <<< "$b"
  for i in 0 1 2 3; do
    [ "${x[i]:-0}" -gt "${y[i]:-0}" ] && return 0
    [ "${x[i]:-0}" -lt "${y[i]:-0}" ] && return 1
  done
  return 0
}

# ─── which system is this ───
# WSL itself, not just its kernel: a Docker container on a WSL machine also says
# "microsoft" in /proc/version, but has neither of these
is_wsl() {
  [ -n "${WSL_DISTRO_NAME:-}" ] || [ -e /proc/sys/fs/binfmt_misc/WSLInterop ] || [ -e /proc/sys/fs/binfmt_misc/WSLInterop-late ]
}

# OS: ubuntu | macos | linux (another distro) · OS_VERSION: 24.04, 26.04, 15.4…
# IS_WSL: 1 inside WSL · ARCH: amd64 | arm64 · HAS_DESKTOP: 1 when fonts matter here
detect_platform() {
  IS_WSL=0 HAS_DESKTOP=0
  case "$(uname -m)" in
    x86_64|amd64) ARCH=amd64 ;;
    arm64|aarch64) ARCH=arm64 ;;
    *) ARCH=$(uname -m) ;;
  esac
  if [ "$(uname -s)" = Darwin ]; then
    OS=macos OS_VERSION=$(sw_vers -productVersion) OS_NAME="macOS $OS_VERSION" HAS_DESKTOP=1
    return
  fi
  OS=linux OS_VERSION="" OS_NAME="Linux"
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    [ "${ID:-}" = ubuntu ] && OS=ubuntu
    OS_VERSION=${VERSION_ID:-} OS_NAME=${PRETTY_NAME:-Linux}
  fi
  if is_wsl; then
    IS_WSL=1 OS_NAME="$OS_NAME (WSL)"
  elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    HAS_DESKTOP=1
  fi
}
