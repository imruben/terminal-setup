#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  The whole install tested in fresh Ubuntu containers (Docker):  tests/install/run.sh [tag…]
#  (default: 24.04 26.04). The repo as it is now (uncommitted changes too) is copied into
#  "~/my repos/terminal-setup" (a space on purpose) and inside.sh runs there as a sudo user:
#  install, versions, zsh, make check, doctor, the tmux monitor tab by tab, autosave, btop
#  sleeping out of sight, a closed pane repaired, install again, uninstall.
#  Prints the PASS / FAIL lines · the full output of each goes to $LOGS (default a temp folder).
#  Nothing on this machine changes but the containers it makes (removed at the end).
# ═══════════════════════════════════════════════════════════════
set -u
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
LOGS=${LOGS:-$(mktemp -d)}
tags=("$@"); [ ${#tags[@]} -gt 0 ] || tags=(24.04 26.04)
command -v docker >/dev/null || { echo "FAIL docker is not installed"; exit 1; }

fails=0
for tag in "${tags[@]}"; do
  name="ts-test-${tag//[^0-9a-z]/}-$$"
  log="$LOGS/ubuntu-$tag.log"
  echo "── ubuntu:$tag  (log: $log)"
  docker run -d --name "$name" -e TZ=Europe/Madrid "ubuntu:$tag" sleep infinity >/dev/null || { echo "FAIL ubuntu:$tag: no container"; fails=$((fails + 1)); continue; }
  docker exec "$name" bash -c 'export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq sudo git ca-certificates curl make locales >/dev/null 2>&1 && locale-gen en_US.UTF-8 >/dev/null
    id ubuntu >/dev/null 2>&1 && userdel -r ubuntu >/dev/null 2>&1
    useradd -m -s /bin/bash tester && echo "tester ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/tester
    mkdir -p "/home/tester/my repos"'
  # the working tree as it is now (.git too: the installer reads the version from it)
  tar -C "$(dirname "$repo")" -cf - "$(basename "$repo")" \
    | docker exec -i "$name" sh -c 'mkdir -p "/home/tester/my repos/terminal-setup" && tar -C "/home/tester/my repos/terminal-setup" --strip-components=1 -xf -'
  docker cp "$here/inside.sh" "$name:/home/tester/inside.sh" >/dev/null
  docker exec "$name" chown -R tester:tester /home/tester
  docker exec -u tester -e HOME=/home/tester -e USER=tester -e LANG=en_US.UTF-8 -w /home/tester "$name" \
    bash /home/tester/inside.sh > "$log" 2>&1
  docker rm -f "$name" >/dev/null 2>&1
  grep -E "^(PASS|FAIL)" "$log" | sed "s/^/  /"
  n=$(grep -c "^FAIL" "$log"); p=$(grep -c "^PASS" "$log")
  if [ "$n" -gt 0 ] || ! grep -q "^DONE" "$log"; then
    echo "✘ ubuntu:$tag: $p passed, $n failed$(grep -q '^DONE' "$log" || echo ', did not finish')"; fails=$((fails + 1))
  else
    echo "✔ ubuntu:$tag: all $p passed"
  fi
done
exit $(( fails > 0 ))
