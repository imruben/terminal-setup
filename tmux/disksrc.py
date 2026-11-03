# ═══════════════════════════════════════════════════════════════
#  What the disk tab knows (tmux/disk_folders.py, tmux/disk_mounts.py, tmux/disk_cleanup.py)
#
#  Disks    the filesystems worth looking at (df), without the pseudo ones
#           (tmpfs, snaps, WSL's driver mounts, macOS's system volumes)
#  Measure  `du -xk FOLDER` in the background: every folder's size in one pass,
#           so moving into a subfolder is instant. Stays on one filesystem (-x).
#  Cleanup  what can be freed on this machine and how (apt, journal, snap, brew,
#           Docker, language caches, old Claude Code versions, the trash…)
# ═══════════════════════════════════════════════════════════════

import json
import os
import re
import shutil
import subprocess
import threading
import time

HOME = os.path.expanduser("~")
MACOS = os.uname().sysname == "Darwin"
WSL = bool(os.environ.get("WSL_DISTRO_NAME")) or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop") \
    or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop-late")
C_ENV = {**os.environ, "LC_ALL": "C"}


def tilde(p):
    return "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p


def human(n):
    if n is None:
        return ""
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024


def ago(stamp):
    """Seconds since the epoch → '45s', '5m', '3h', '2d', '4mo', '1y' (None → '')."""
    if not stamp:
        return ""
    secs = max(0, int(time.time() - stamp))
    for n, unit in ((86400 * 365, "y"), (86400 * 30, "mo"), (86400 * 7, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if secs >= n:
            return f"{secs // n}{unit}"
    return f"{secs}s"


def run_text(*argv, timeout=60):
    try:
        return subprocess.run(argv, capture_output=True, text=True, env=C_ENV, timeout=timeout,
                              stdin=subprocess.DEVNULL, errors="replace").stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def bar(fraction, width=10):
    """'██████░░░░' for 0.6 · the last cell shows eighths so small differences show."""
    fraction = max(0.0, min(1.0, fraction or 0.0))
    full, rest = divmod(round(fraction * width * 8), 8)
    return ("█" * full + ("▏▎▍▌▋▊▉"[rest - 1] if rest else "")).ljust(width, "░")[:width]


# ─── Disks ───
SKIP_TYPES = {"tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "cgroup", "cgroup2", "devpts", "mqueue",
              "debugfs", "tracefs", "securityfs", "pstore", "bpf", "configfs", "fusectl", "hugetlbfs", "autofs",
              "efivarfs", "rootfs", "binfmt_misc", "fuse.snapfuse", "nsfs", "ramfs", "devfs", "nullfs", "fuse.portal",
              "fuse.gvfsd-fuse", "fuse.lxcfs", "rpc_pipefs", "selinuxfs"}
SKIP_PREFIX = ("/snap/", "/usr/lib/wsl", "/usr/lib/modules", "/usr/lib/linux-tools", "/mnt/wsl", "/mnt/wslg", "/run",
               "/dev", "/sys", "/proc", "/init", "/var/lib/docker", "/var/snap", "/boot/efi",
               "/System/Volumes/VM", "/System/Volumes/Preboot", "/System/Volumes/Update", "/System/Volumes/xarts",
               "/System/Volumes/iSCPreboot", "/System/Volumes/Hardware", "/private/var/vm", "/Library/Developer/CoreSimulator")


def mac_types():
    """{mount point: type} from `mount` (macOS's df has no type column)."""
    out = {}
    for line in run_text("mount", timeout=10).splitlines():
        m = re.match(r".+? on (.+) \(([^,)]+)", line)
        if m:
            out[m[1]] = m[2]
    return out


def mounts():
    """[{mount, label, device, type, size, used, free}] in bytes, the system disk first."""
    if MACOS:
        text, types = run_text("df", "-kP", timeout=10), mac_types()
    else:
        text, types = run_text("df", "-kPT", timeout=10), None
    rows, seen = [], set()
    for line in text.splitlines()[1:]:
        parts = line.split()
        if types is None:
            if len(parts) < 7 or not (parts[2].isdigit() and parts[3].isdigit() and parts[4].isdigit()):
                continue
            dev, kind, size, used, free = parts[0], parts[1], int(parts[2]), int(parts[3]), int(parts[4])
            mnt = " ".join(parts[6:])
        else:
            if len(parts) < 6 or not (parts[1].isdigit() and parts[2].isdigit() and parts[3].isdigit()):
                continue
            dev, size, used, free = parts[0], int(parts[1]), int(parts[2]), int(parts[3])
            mnt = " ".join(parts[5:])
            kind = types.get(mnt, "")
        if (kind in SKIP_TYPES and mnt != "/") or size == 0:       # / always (a container's is overlay)
            continue
        if MACOS and mnt == "/":
            continue                    # the sealed system volume: your files are on …/Data
        if any(mnt == p.rstrip("/") or mnt.startswith(p.rstrip("/") + "/") for p in SKIP_PREFIX):
            continue                    # /dev/…, not /development
        if kind == "9p" and not re.match(r"^/mnt/[a-z]$", mnt):
            continue                    # WSL: only the Windows drives (C:, D:…)
        if (dev, kind) in seen and not dev.startswith(("none", "map")):
            continue                    # the same filesystem mounted twice (bind mounts)
        seen.add((dev, kind))
        rows.append({"mount": mnt, "label": label(mnt, dev), "device": dev, "type": kind,
                     "size": size * 1024, "used": used * 1024, "free": free * 1024})
    rows.sort(key=lambda r: (r["mount"] not in ("/", "/System/Volumes/Data"), r["mount"]))
    return rows


def label(mnt, dev):
    m = re.match(r"^/mnt/([a-z])$", mnt)
    if WSL and m:
        return f"Windows {m[1].upper()}:"
    if mnt == "/":
        return "WSL disk" if WSL else "system"
    if mnt == "/System/Volumes/Data":
        return "Macintosh HD"
    if mnt.startswith("/Volumes/"):
        return mnt[9:]
    return os.path.basename(mnt) or mnt


_mounts = [0.0, ()]


def mount_points():
    """Every mount point (/proc/self/mounts, or `mount` on macOS), kept 10 s."""
    if time.monotonic() - _mounts[0] < 10:
        return _mounts[1]
    found = []
    try:
        with open("/proc/self/mounts", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 1:
                    found.append(parts[1].replace("\\040", " ").replace("\\011", "\t"))
    except OSError:
        for line in run_text("mount", timeout=10).splitlines():
            m = re.match(r".+? on (.+) \(", line)
            if m:
                found.append(m[1])
    _mounts[0], _mounts[1] = time.monotonic(), tuple(found)
    return _mounts[1]


def mounts_under(path):
    """The disks mounted inside path (a delete must never reach them)."""
    pre = path.rstrip("/") + "/"
    return [m for m in mount_points() if m.startswith(pre)]


# ─── Measure: du in the background ───
def device(path):
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def short(path, width=40):
    """~/a/very/long/path → …/long/path when it is longer than width."""
    p = tilde(path)
    if len(p) <= width:
        return p
    parts, out = p.split("/"), ""
    for part in reversed(parts):
        if len(out) + len(part) + 2 > width:
            break
        out = "/" + part + out
    return "…" + (out or "/" + parts[-1][-(width - 2):])


class Measure:
    """du -xk ROOT, read as it goes: sizes[folder] = bytes for every folder under ROOT
    (on the same filesystem). unreadable: folders du could not read (no permission),
    so their sizes and their parents' are lower bounds."""

    def __init__(self, root, on_progress):
        self.root, self.on_progress = root, on_progress
        self.sizes, self.unreadable = {}, set()
        self.done, self.cancelled, self.count = False, False, 0
        self.started, self.finished = time.time(), None
        self.proc = None
        self.dev = device(root)
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        try:
            self.proc = subprocess.Popen(["du", "-xk", self.root], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         stdin=subprocess.DEVNULL, env=C_ENV)
        except OSError:
            self.finished = time.time()
            self.done = True
            self.on_progress()
            return
        if self.cancelled:                       # cancelled before du started
            self.cancel()
        threading.Thread(target=self.errors, daemon=True).start()
        last = time.monotonic()
        for raw in self.proc.stdout:
            kb, _, path = raw.decode("utf-8", "surrogateescape").rstrip("\n").partition("\t")
            if kb.isdigit():
                self.sizes[path] = int(kb) * 1024
                self.count += 1
            if time.monotonic() - last > 0.5:
                last = time.monotonic()
                self.on_progress()
        self.proc.wait()
        self.finished = time.time()              # before done: a reader seeing done finds finished set
        self.done = True
        self.on_progress()

    def errors(self):
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "surrogateescape")
            m = re.search(r"cannot (?:read directory|access) '(.+?)'", line) or re.match(r"du: (.+?): ", line)
            if m:
                self.unreadable.add(m[1])

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass

    def covers(self, path):
        """path is inside the measured folder and on the same disk (du -x does not go further)."""
        return (path == self.root or path.startswith(self.root.rstrip("/") + "/")) and device(path) == self.dev

    def partial(self, path):
        """Some folder at or under path could not be read: its size is a lower bound."""
        pre = path.rstrip("/") + "/"
        return any(u == path or u.startswith(pre) for u in tuple(self.unreadable))   # du adds to it meanwhile


# ─── Cleanup ───
def du_bytes(path, timeout=120):
    if not os.path.exists(path):
        return None
    out = run_text("du", "-sk", path, timeout=timeout).split("\t", 1)[0].strip()
    return int(out) * 1024 if out.isdigit() else None


def unit_bytes(text, decimal=False):
    """'7.815GB' · '64M' · '8.192kB' → bytes. Docker counts in powers of 1000 (decimal=True);
    journalctl and brew in powers of 1024."""
    m = re.match(r"([\d.]+)\s*([kKMGT]?)", (text or "").strip())
    if not m:
        return None
    base = 1000 if decimal else 1024
    return int(float(m[1]) * base ** " KMGT".index(m[2].upper() or " "))


def apt_autoremove():
    names = [l.split()[1] for l in run_text("apt-get", "-s", "autoremove").splitlines() if l.startswith("Remv ")]
    if not names:
        return 0, "nothing"
    kb = sum(int(x) for x in run_text("dpkg-query", "-W", "-f=${Installed-Size}\n", *names).split() if x.isdigit())
    return kb * 1024, f"{len(names)} package{'s' if len(names) != 1 else ''}"


def journal_size():
    m = re.search(r"take up ([\d.]+[KMGT]?)", run_text("journalctl", "--disk-usage", timeout=20))
    return (unit_bytes(m[1]), "up to (keeps 7 days)") if m else (None, "")


def snap_old():
    total, n = 0, 0
    for line in run_text("snap", "list", "--all").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and "disabled" in line:
            p = f"/var/lib/snapd/snaps/{parts[0]}_{parts[2]}.snap"
            if os.path.exists(p):
                total += os.path.getsize(p)
                n += 1
    return total, f"{n} old revision{'s' if n != 1 else ''}"


def brew_cleanup():
    m = re.search(r"free approximately ([\d.]+\s*[KMGT]?B)", run_text("brew", "cleanup", "-n", "--prune=all", timeout=120))
    return (unit_bytes(m[1].replace(" ", "")), "") if m else (0, "")


_docker = {"at": 0.0, "data": {}}
_docker_lock = threading.Lock()


def docker_df():
    """{'Images': (reclaimable bytes, 'N unused of M'), …} from `docker system df`, kept 30 s."""
    with _docker_lock:
        if time.monotonic() - _docker["at"] < 30:
            return _docker["data"]
        data = {}
        for line in run_text("docker", "system", "df", "--format", "{{json .}}", timeout=30).splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            total, active = d.get("TotalCount", "0"), d.get("Active", "0")
            unused = int(total) - int(active) if str(total).isdigit() and str(active).isdigit() else 0
            data[d.get("Type")] = (unit_bytes(d.get("Reclaimable", "0B").split(" ")[0], decimal=True) or 0,
                                   f"{unused} unused of {total}", unused > 0)
        _docker.update(at=time.monotonic(), data=data)
        return data


def forget_docker():
    """Ask docker again next time (after something was cleaned)."""
    with _docker_lock:
        _docker["at"] = 0.0


CLAUDE_VERSIONS = os.path.join(HOME, ".local", "share", "claude", "versions")


def claude_versions():
    """Old Claude Code versions next to the one ~/.local/bin/claude runs · nothing when that
    one is not among them (then which one runs is not known: none is called old)."""
    d = CLAUDE_VERSIONS
    current = os.path.realpath(os.path.join(HOME, ".local", "bin", "claude"))
    try:
        names = os.listdir(d)
    except OSError:
        return [], 0
    if os.path.dirname(current) != os.path.realpath(d):
        return [], 0
    old, total = [], 0
    for n in names:
        p = os.path.join(d, n)
        if os.path.realpath(p) == current:
            continue
        try:
            total += os.path.getsize(p) if os.path.isfile(p) else 0
        except OSError:
            continue
        old.append(p)
    return old, total


def cache_dir(linux, mac):
    return os.path.join(HOME, mac if MACOS else linux)


class Item:
    """Something that can be cleaned. size() → (bytes or None, note[, can clean although small]).
    cmd: the shell command, or a function that gives it when you clean (what it removes then)."""

    def __init__(self, id, label, why, size, cmd, sudo=False, path=None, warn="", tool=None, how=None):
        self.id, self.label, self.why, self.size_fn, self.cmd = id, label, why, size, cmd
        self.sudo, self.path, self.warn, self.tool = sudo, path, warn, tool
        self.how = how or (cmd if isinstance(cmd, str) else "")

    def command(self):
        return self.cmd() if callable(self.cmd) else self.cmd


def quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def rm_cmd(path):
    return f"rm -rf -- {quote(path)}"


def empty_cmd(path):
    """Everything inside path, hidden files too, the folder itself stays."""
    return f"find {quote(path)} -mindepth 1 -delete"


def items():
    """What this machine has that can be cleaned (each knows its size and how to clean it)."""
    have = shutil.which
    out = []
    if have("apt-get") and not MACOS:
        out.append(Item("apt-cache", "apt: downloaded packages", "the .deb files apt keeps after installing",
                        lambda: (du_bytes("/var/cache/apt/archives"), ""), "sudo apt-get clean", sudo=True,
                        path="/var/cache/apt/archives"))
        out.append(Item("apt-auto", "apt: packages nothing needs", "dependencies left behind by removed packages",
                        apt_autoremove, "sudo apt autoremove --purge", sudo=True))
    if have("journalctl") and os.path.isdir("/run/systemd/system"):
        out.append(Item("journal", "system logs (journal)", "keeps the last 7 days, at most 50M",
                        journal_size, "sudo journalctl --vacuum-time=7d --vacuum-size=50M", sudo=True,
                        path="/var/log/journal"))
    if have("snap") and os.path.isdir("/var/lib/snapd/snaps"):
        out.append(Item("snap", "snap: old revisions", "snap keeps the previous version of every snap",
                        snap_old, "snap list --all | awk '/disabled/ {print $1, $3}' | while read -r n r; do "
                                  "sudo snap remove \"$n\" --revision=\"$r\"; done", sudo=True))
    if have("brew"):
        out.append(Item("brew", "Homebrew: old versions and downloads", "brew cleanup --prune=all",
                        brew_cleanup, "brew cleanup --prune=all", path=run_text("brew", "--cache", timeout=20).strip() or None))
    if have("docker"):
        for key, id, lbl, cmd, warn in (
                ("Build Cache", "docker-build", "Docker: build cache", "docker builder prune -a -f",
                 "the next builds start from scratch (slower once)"),
                ("Images", "docker-images", "Docker: unused images", "docker image prune -a -f",
                 "images no container uses: pulled or built again when needed"),
                ("Containers", "docker-containers", "Docker: stopped containers", "docker container prune -f",
                 "stopped containers are removed (with what they wrote outside volumes)"),
                ("Local Volumes", "docker-volumes", "Docker: unused volumes", "docker volume prune -a -f",
                 "DATA: volumes no container uses (old databases…) are deleted for good")):
            out.append(Item(id, lbl, warn, lambda key=key: docker_df().get(key, (None, "", False)), cmd, warn=warn,
                            tool="docker"))
    for id, lbl, linux, mac, tool_cmd in (
            ("pip", "pip downloads", ".cache/pip", "Library/Caches/pip", None),
            ("npm", "npm cache", ".npm/_cacache", ".npm/_cacache", None),
            ("yarn", "yarn cache", ".cache/yarn", "Library/Caches/Yarn", None),
            ("pnpm", "pnpm store (unused packages)", ".local/share/pnpm/store", "Library/pnpm/store", "pnpm store prune"),
            ("composer", "Composer cache", ".cache/composer", "Library/Caches/composer", None),
            ("go", "Go build cache", ".cache/go-build", "Library/Caches/go-build", "go clean -cache"),
            ("playwright", "Playwright browsers", ".cache/ms-playwright", "Library/Caches/ms-playwright", None),
            ("puppeteer", "Puppeteer browsers", ".cache/puppeteer", ".cache/puppeteer", None),
            ("thumbnails", "thumbnails", ".cache/thumbnails", "", None),
            ("derived", "Xcode DerivedData", "", "Library/Developer/Xcode/DerivedData", None)):
        sub = mac if MACOS else linux
        if not sub:
            continue
        path = os.path.join(HOME, sub)
        if not os.path.isdir(path):
            continue
        tool = tool_cmd.split()[0] if tool_cmd else None
        cmd = tool_cmd if tool_cmd and have(tool) else rm_cmd(path)
        note = "up to (unused ones)" if tool_cmd and have(tool) and id == "pnpm" else ""
        out.append(Item(id, lbl, f"downloaded again when needed · {tilde(path)}",
                        lambda path=path, note=note: (du_bytes(path), note), cmd, path=path))
    if os.path.isdir(CLAUDE_VERSIONS):
        def claude_size():
            old, total = claude_versions()
            return total, f"{len(old)} old" if old else "nothing"
        out.append(Item("claude", "Claude Code: old versions", "every update keeps the previous ones",
                        claude_size, lambda: " ; ".join(rm_cmd(p) for p in claude_versions()[0]) or "true",
                        path=CLAUDE_VERSIONS, how="rm the versions ~/.local/bin/claude does not run"))
    trash = os.path.join(HOME, ".Trash" if MACOS else ".local/share/Trash")
    if os.path.isdir(trash):
        out.append(Item("trash", "trash", "what you deleted from a file manager",
                        lambda: (du_bytes(trash), ""), empty_cmd(trash), path=trash))
    logs = os.path.join(HOME, ".tmux", "logs")
    if os.path.isdir(logs):
        out.append(Item("tmux-logs", "tmux logs (Ctrl+a P)", "the panes you logged or saved",
                        lambda: (du_bytes(logs), ""), empty_cmd(logs), path=logs))
    return out
