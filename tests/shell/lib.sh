#!/usr/bin/env bash
# shellcheck disable=SC2088,SC2034   # "~/x" is the text expected · SHA_… are read by download() through ${!var}
# ═══════════════════════════════════════════════════════════════
#  The installer's shell functions, in seconds (the whole install takes 15 minutes):
#  install/lib.sh (versions, paths, dry-run, downloads checked by sha256, which system) and the
#  block install/config.sh puts in your ~/.zshrc and ~/.tmux.conf (added once, refreshed in
#  place, your lines kept, taken out again exactly).      tests/shell/lib.sh
#  Plain bash, no framework · a fake HOME in a temp folder: nothing of yours is touched.
#  lib.sh is meant for macOS's bash 3.2 too:  docker run --rm -v "$PWD:/r" -w /r bash:3.2 bash tests/shell/lib.sh
# ═══════════════════════════════════════════════════════════════
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME"
# shellcheck source=install/lib.sh
. "$ROOT/install/lib.sh"
passed=0 failed=0
is() {   # is <what> <got> <want>
  if [ "$2" = "$3" ]; then passed=$((passed + 1)); else failed=$((failed + 1)); printf 'FAIL %s\n  got:  %s\n  want: %s\n' "$1" "$2" "$3"; fi
}
yes_() { if "$@"; then echo yes; else echo no; fi; }

# ─── version_ge ───
for c in "3.6 3.6 yes" "3.6a 3.6 yes" "3.5 3.6 no" "3.10 3.9 yes" "3.9 3.10 no" "next-3.7 3.6 yes" \
         "0.48.1 0.48 yes" "0.47.9 0.48 no" "1.2.3.4 1.2.3.5 no" "2 1.99 yes" "tmux 3.6a 3.6 yes" "v1.0 1 yes"; do
  set -- $c
  [ $# = 4 ] && set -- "$1 $2" "$3" "$4"           # "tmux 3.6a": the name in front is skipped
  is "version_ge $1 $2" "$(yes_ version_ge "$1" "$2")" "$3"
done

# ─── paths ───
is "repo_path without spaces" "$(repo_path /home/me/terminal-setup)" /home/me/terminal-setup
is "repo_path with a space" "$(repo_path "/home/me/my repos/terminal-setup")" "$HOME/.local/share/terminal-setup"
is "repo_path with a tab" "$(repo_path "$(printf '/a\tb')")" "$HOME/.local/share/terminal-setup"
is "tilde in home" "$(tilde "$HOME/x/y")" "~/x/y"
is "tilde elsewhere" "$(tilde /etc/x)" /etc/x
is "PATH has ~/.local/bin" "$(case ":$PATH:" in (*":$HOME/.local/bin:"*) echo yes ;; (*) echo no ;; esac)" yes   # ((: bash 3.2)

# ─── run / ask ───
DRY_RUN=1
out=$(run touch "$T/made")
is "dry-run changes nothing" "$(yes_ test -e "$T/made")" no
is "dry-run says what it would do" "$(printf '%s' "$out" | sed 's/\x1b\[[0-9;]*m//g')" "    [dry-run] touch $T/made"
DRY_RUN=0
run touch "$T/made"
is "run runs" "$(yes_ test -e "$T/made")" yes
is "ask with --yes" "$(ASSUME_YES=1 yes_ ask "go?")" yes

# ─── download: checked against its sha256 (with curl, as the install needs it) ───
if have curl; then
  printf 'the file\n' > "$T/src"
  if have sha256sum; then sum=$(sha256sum "$T/src"); else sum=$(shasum -a 256 "$T/src"); fi
  SHA_good=${sum%% *} SHA_bad=0000000000000000000000000000000000000000000000000000000000000000
  ( download "file://$T/src" "$T/got" good ) >/dev/null 2>&1
  is "download with the right sha256" "$(cat "$T/got" 2>/dev/null)" "the file"
  ( download "file://$T/src" "$T/bad" bad ) >/dev/null 2>"$T/err"; rc=$?
  is "download with a wrong sha256 fails" "$rc" 1
  is "and leaves no file" "$(yes_ test -e "$T/bad")" no
  is "and says why" "$(grep -c "checksum is not the expected one" "$T/err")" 1
  ( download "file://$T/src" "$T/none" missing ) >/dev/null 2>&1; rc=$?
  is "download with no checksum known fails" "$rc" 1
else
  echo "– no curl here: the download checks are skipped"
fi

# ─── which system ───
mkdir -p "$T/bin"
printf '#!/bin/sh\ncase $1 in -m) echo aarch64 ;; -s) echo Linux ;; esac\n' > "$T/bin/uname"; chmod +x "$T/bin/uname"
( PATH="$T/bin:$PATH"; unset WSL_DISTRO_NAME; detect_platform; echo "$ARCH" ) > "$T/arch"
is "aarch64 is arm64" "$(cat "$T/arch")" arm64
( WSL_DISTRO_NAME=Ubuntu; detect_platform; echo "$IS_WSL $OS_NAME" ) > "$T/wsl"
is "WSL seen" "$(cut -d' ' -f1 "$T/wsl")" 1
is "and said in the name" "$(grep -c '(WSL)$' "$T/wsl")" 1

# ─── which version (git describe) ───
if have git; then
  g="$T/repo"; mkdir -p "$g"
  G() { git -C "$g" -c user.email=t@t -c user.name=t -c commit.gpgsign=false -c tag.gpgsign=false "$@" >/dev/null 2>&1; }
  G init -q; echo a > "$g/f"; G add f; G commit -qm one
  is "no release yet: the commit" "$(repo_version "$g")" "$(git -C "$g" rev-parse --short HEAD)"
  G tag -a v1.0.0 -m 1.0.0
  is "a release" "$(repo_version "$g")" v1.0.0
  G tag other-tag                                       # tags that are not versions do not count
  echo b > "$g/f"; G commit -qam two
  is "a commit after it" "$(repo_version "$g" | sed 's/-g[0-9a-f]*$/-gX/')" v1.0.0-1-gX
  echo c > "$g/f"
  is "changes not committed" "$(repo_version "$g" | sed 's/-g[0-9a-f]*-/-gX-/')" v1.0.0-1-gX-dirty
  is "no git there" "$(repo_version "$T/nowhere")" unknown
else
  echo "– no git here: the version checks are skipped"
fi

# ─── the block in ~/.zshrc (install/config.sh) ───
REPO=/repo/one BACKUP_DIR="$T/backup"
# shellcheck source=install/config.sh
. "$ROOT/install/config.sh"
rc="$HOME/.zshrc"
printf 'export A=1\nalias x=y' > "$rc"                       # a last line with no newline
before=$(cat "$rc")
add_block "$rc" "$(block_zsh)" >/dev/null
is "added at the end" "$(tail -1 "$rc")" "$MARK_END"
is "the source line" "$(grep -c '^source "/repo/one/zsh/zshrc"$' "$rc")" 1
is "the last line of yours kept whole" "$(grep -cx 'alias x=y' "$rc")" 1
is "a backup of the file as it was" "$(cat "$BACKUP_DIR/.zshrc")" "$before"
once=$(cat "$rc")
add_block "$rc" "$(block_zsh)" >/dev/null
is "a second install changes nothing" "$(cat "$rc")" "$once"
printf 'export AFTER=1\n' >> "$rc"                             # yours, after the block
REPO="/repo/two"
add_block "$rc" "$(block_zsh)" >/dev/null
is "the repo moved: the block refreshed in place" "$(grep -c 'repo/two' "$rc") $(grep -c 'repo/one' "$rc")" "1 0"
is "your lines after it stay after it" "$(tail -1 "$rc")" "export AFTER=1"
is "one block only" "$(grep -c "^$MARK_BEGIN" "$rc")" 1
is "taken out: your lines exactly" "$(without_block "$rc")" "$(printf '%s\nexport AFTER=1' "$before")"
printf '  %s\n' "$MARK_BEGIN" > "$T/indented"
is "a mark not at the start of a line is not one" "$(yes_ has_block "$T/indented")" no
printf 'a\n%s\nsource x\n' "$MARK_BEGIN" > "$T/broken"
( check_marks "$T/broken" ) >/dev/null 2>&1; rc_=$?
is "a begin mark with no end stops the install" "$rc_" 1
new="$HOME/.config/new/file"
add_block "$new" "$(block_tmux)" >/dev/null
is "a file that was not there: only the block" "$(cat "$new")" "$(block_tmux)"
is "the tmux block names the repo" "$(grep -c '^TERMINAL_SETUP="/repo/two"$' "$new")" 1

echo "$passed passed, $failed failed"
[ "$failed" = 0 ]
