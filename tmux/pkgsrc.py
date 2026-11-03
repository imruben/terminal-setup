# ═══════════════════════════════════════════════════════════════
#  Package sources for the `packages` tab: apt, snap, Homebrew
#  (packages.py, updates.py, pkgsearch.py, pkginfo.py all go through here)
#
#  Each source answers the same questions: the packages you installed yourself,
#  pending updates, search, details / files / dependencies, and the commands to
#  install, uninstall, upgrade and check. A source only shows up when it is there:
#  snap when snapd runs, brew once Homebrew is installed (/opt/homebrew or /usr/local on
#  macOS, /home/linuxbrew on Linux).
#
#  A package is "source:name" everywhere (@pkg-selected, row ids). Notes (why you
#  installed it) stay in ~/.apt-notes.tsv: apt ones by name as before, the others
#  as snap:name / brew:name.
#  Also a command, for the `installed-packages` shell function (zsh/functions.zsh):
#    pkgsrc.py mine [source]   the packages you installed: source name version description
#    pkgsrc.py find NAME       NAME wherever it is installed (also as a dependency)
#    pkgsrc.py sources         the sources there are
#    pkgsrc.py base            (re)build ~/.apt-base.txt, the apt packages the system came with
#  (tab-separated lines)
#  Slow answers (brew, the snap store) come from Background: a pane gets what is
#  known now and redraws when the rest arrives, so it never freezes.
# ═══════════════════════════════════════════════════════════════

import glob
import gzip
import http.client
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import threading
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))     # also when run as a command
from tui import BLUE, BOLD, DIM, GREEN, RESET, SUB, TEXT, YELLOW

NOTES = os.path.expanduser("~/.apt-notes.tsv")
C_ENV = {**os.environ, "LC_ALL": "C"}


def run_text(*argv, env=None, timeout=60):
    try:
        return subprocess.run(argv, capture_output=True, text=True, env=env or C_ENV, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def human(n):
    if n is None:
        return ""
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024


def dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def k(label):
    return f"  {DIM}{label:<11}{RESET}"


def wrap_lines(text, width, colour=SUB):
    import textwrap
    out = []
    for para in (text or "").split("\n\n"):
        for line in textwrap.wrap(" ".join(para.split()), max(20, width - 6)) or [""]:
            out.append(f"  {colour}{line}")
        out.append("")
    return out


# ─── notes: why you installed it ───
def note_key(src, name):
    return name if src == "apt" else f"{src}:{name}"


def read_notes():
    notes = {}
    try:
        with open(NOTES, encoding="utf-8") as f:
            for line in f:
                pkg, _, why = line.rstrip("\n").partition("\t")
                if pkg:
                    notes[pkg] = why
    except FileNotFoundError:
        pass
    return notes


def write_notes(notes):
    """Written to a new file that then takes the old one's place: a crash or a full disk
    halfway through cannot leave ~/.apt-notes.tsv empty."""
    target = os.path.realpath(NOTES)          # through a link (dotfiles): its target changes
    tmp = f"{target}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        for pkg in sorted(notes):
            f.write(f"{pkg}\t{notes[pkg]}\n")
    os.replace(tmp, target)


def split_id(pkg_id):
    """'snap:hello' → ('snap', 'hello') · a plain name is apt (older selections)."""
    src, sep, name = (pkg_id or "").partition(":")
    return (src, name) if sep and src in SOURCES else ("apt", pkg_id or "")


# ═══ apt ═══
class Apt:
    name = "apt"
    sudo = True
    BASE = os.path.expanduser("~/.apt-base.txt")
    LINE = re.compile(r"^(\S+)/(\S+)\s+(\S+)\s+(\S+)\s+\[upgradable from: ([^\]]+)\]")
    error = ""
    base_count = 0

    @staticmethod
    def available():
        return shutil.which("apt-get") is not None

    _arch = None

    @classmethod
    def arch(cls):
        """This machine's own architecture (amd64…): other ones are shown as name:arch."""
        if cls._arch is None:
            cls._arch = run_text("dpkg", "--print-architecture").strip() or "?"
        return cls._arch

    def held(self):
        """Packages on hold (apt-mark hold): `apt upgrade` keeps them back."""
        return set(run_text("apt-mark", "showhold").split())

    tried_base = False              # build_base() failed once: not again every reload

    @staticmethod
    def image_packages():
        """The packages the system came with: the apt line that built the image (WSL, cloud
        images) or the installer's list (desktop / server installs). None when neither is left."""
        found = set()
        for log in glob.glob("/var/log/apt/history.log*"):
            try:
                with (gzip.open if log.endswith(".gz") else open)(log, "rt", errors="replace") as f:
                    for line in f:
                        if "AutoInstall=yes install " in line:
                            found.update(line.split(" install ", 1)[1].split())
            except OSError:
                pass
        if found:
            return found
        try:
            with gzip.open("/var/log/installer/initial-status.gz", "rt", errors="replace") as f:
                found = {l.split(":", 1)[1].strip() for l in f if l.startswith("Package:")}
        except OSError:
            pass
        return found or None

    def build_base(self):
        """Write ~/.apt-base.txt from image_packages() · the number of packages, or None."""
        base = self.image_packages()
        if base is None:
            return None
        with open(self.BASE, "w") as f:
            f.write("".join(f"{p}\n" for p in sorted(base)))
        return len(base)

    def base(self):
        try:
            with open(self.BASE) as f:
                return {l.strip() for l in f if l.strip()}
        except FileNotFoundError:
            pass
        if not self.tried_base:
            self.tried_base = True
            if self.build_base() is not None:
                return self.base()
        return None

    def mine(self):
        """Manual packages minus the ones the system came with (same as `installed-packages`)."""
        base = self.base()
        if base is None:
            self.error, self.base_count, base = ("apt: no record of the packages the system came with "
                                                 "(apt history rotated?): showing every manual one"), 0, set()
        else:
            self.error, self.base_count = "", len(base)
        mine = sorted(set(run_text("apt-mark", "showmanual").split()) - base)
        if not mine:
            return []
        out = run_text("dpkg-query", "-W", "-f", "${binary:Package}\t${Version}\t${Installed-Size}\t${binary:Summary}\n",
                       *mine)
        native = f":{self.arch()}"
        rows = []
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) >= 4:
                name = p[0][:-len(native)] if p[0].endswith(native) else p[0]      # zlib1g · wine32:i386
                rows.append({"name": name, "version": p[1], "size": int(p[2]) * 1024 if p[2].isdigit() else None,
                             "desc": p[3]})
        return rows

    def updates(self):
        rows, held, native = [], self.held(), self.arch()
        for line in run_text("apt", "list", "--upgradable").splitlines():
            m = self.LINE.match(line)
            if m:
                name, suite, new, arch, old = m.groups()
                if arch not in (native, "all"):       # another architecture: its own package
                    name = f"{name}:{arch}"
                rows.append({"name": name, "old": old, "new": new, "origin": suite.split(",")[0],
                             "security": "security" in suite, "held": name in held})
        return rows

    def checked(self):
        stamp = next((p for p in ("/var/lib/apt/periodic/update-success-stamp", "/var/cache/apt/pkgcache.bin")
                      if os.path.exists(p)), None)
        return os.path.getmtime(stamp) if stamp else None

    def search(self, words):
        # apt-cache takes regular expressions: what you type is meant literally (c++, [)
        words = [re.sub(r"([.^$*+?()[\]{}|\\])", r"\\\1", w) for w in words]
        found = []
        for line in run_text("apt-cache", "search", "--", *words).splitlines():
            name, _, desc = line.partition(" - ")
            found.append({"name": name, "desc": desc, "installed": ""})
        return found

    def mark_installed(self, rows):
        """Which rows are installed · asked 2000 names at a time (a search for 'lib' finds ~20 000)."""
        inst = {}
        names = [r["name"] for r in rows]
        for i in range(0, len(names), 2000):
            st = run_text("dpkg-query", "-W", "-f", "${Package}\t${Status}\t${Version}\n", *names[i:i + 2000])
            inst.update({p[0]: p[2] for p in (l.split("\t") for l in st.splitlines())
                         if len(p) == 3 and p[1].endswith(" installed")})
        for r in rows:
            r["installed"] = inst.get(r["name"], "")

    def info(self, name, width, note):
        policy = run_text("apt-cache", "policy", name)
        if not policy.strip():
            return [f"  {YELLOW}apt does not know a package called {name}"]
        inst = cand = ""
        for line in policy.splitlines():
            line = line.strip()
            if line.startswith("Installed:"):
                inst = line.split(":", 1)[1].strip()
            elif line.startswith("Candidate:"):
                cand = line.split(":", 1)[1].strip()
        fields, desc, cur = {}, [], None
        for line in run_text("apt-cache", "show", "--no-all-versions", name).splitlines():
            if line.startswith(" ") and cur == "Description":
                desc.append(line[1:] if line.strip() != "." else "")
            elif ":" in line and not line.startswith(" "):
                cur, _, val = line.partition(":")
                fields[cur] = val.strip()
                if cur in ("Description", "Description-en"):      # not Description-md5
                    cur = "Description"
                    desc = [val.strip()]
        installed = inst and inst != "(none)"
        lines = [k("Package") + f"{BOLD}{TEXT}{name}{RESET}  {DIM}apt"]
        lines.append(k("Installed") + (f"{GREEN}{inst}" if installed else f"{DIM}no"))
        if cand and cand != inst:
            lines.append(k("Available") + f"{YELLOW if installed else TEXT}{cand}"
                         + (f"{DIM}  (update pending)" if installed else ""))
        if note:
            lines.append(k("Why") + f"{YELLOW}{note}")
        for key, label in (("Section", "Section"), ("Installed-Size", "Size"), ("Homepage", "Homepage"),
                           ("Maintainer", "Maintainer")):
            if fields.get(key):
                val = fields[key]
                if key == "Installed-Size" and val.isdigit():
                    val = human(int(val) * 1024)
                lines.append(k(label) + (f"{BLUE}{val}" if key == "Homepage" else f"{SUB}{val}"))
        if desc:
            lines += ["", f"  {TEXT}{desc[0]}", ""] + wrap_lines("\n".join(desc[1:]), width)
        return lines

    def files(self, name):
        out = run_text("dpkg", "-L", name)
        if not out.strip() or "is not installed" in out:
            return None
        return [p for p in out.splitlines() if p.startswith("/") and p != "/."]     # not "diverted by…" lines

    def depends(self, name):
        deps = [l.strip() for l in run_text("apt-cache", "depends", "--important", name).splitlines()[1:] if l.strip()]
        rdeps = sorted({l.strip() for l in run_text("apt-cache", "rdepends", "--installed", "--important",
                                                     name).splitlines()[2:] if l.strip()})
        return deps, rdeps

    def install(self, name, row=None):
        return f"sudo apt install {shlex.quote(name)}"

    def remove(self, name):
        return f"sudo apt remove {shlex.quote(name)}"

    def upgrade(self, name):
        return f"sudo apt install --only-upgrade {shlex.quote(name)}"

    def upgrade_all(self):
        return "sudo apt upgrade"

    def check(self):
        return "sudo apt update"


# ═══ snap (snapd's REST API on its socket: fast, and it knows everything) ═══
class _UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/run/snapd.socket")


class Snap:
    name = "snap"
    sudo = True
    SOCKET = "/run/snapd.socket"
    error = ""

    @classmethod
    def available(cls):
        return shutil.which("snap") is not None and os.path.exists(cls.SOCKET)

    def api(self, path, timeout=20, must=False):
        """snapd's answer · None when it fails (must=True: raises instead, so a pane keeps
        what it knew rather than showing nothing: snapd not up yet, no network for the store)."""
        try:
            c = _UnixHTTP("localhost", timeout=timeout)
            c.request("GET", path)
            d = json.loads(c.getresponse().read())
            c.close()
        except (OSError, ValueError, http.client.HTTPException):
            if must:
                raise OSError(f"snapd did not answer {path}")
            return None
        if d.get("type") != "sync":
            if must and not (d.get("result") or {}).get("kind") == "snap-not-found":
                raise OSError(f"snapd: {(d.get('result') or {}).get('message', 'error')}")
            return None
        return d.get("result")

    def installed(self, must=False):
        return {s["name"]: s for s in (self.api("/v2/snaps", must=must) or [])}

    def mine(self):
        """Apps you installed: not the bases, snapd itself, or content snaps (themes,
        runtimes) that come along as dependencies — those have no commands."""
        rows = []
        for s in self.installed(must=True).values():
            if s.get("type") == "app" and s.get("apps"):
                rows.append({"name": s["name"], "version": s.get("version", ""), "size": s.get("installed-size"),
                             "desc": s.get("summary", "")})
        return rows

    def updates(self):
        local = self.installed(must=True)
        rows = []
        for s in self.api("/v2/find?select=refresh", must=True) or []:
            old = local.get(s["name"], {}).get("version", "")
            rows.append({"name": s["name"], "old": old, "new": s.get("version", ""),
                         "origin": s.get("channel", "") or "stable", "security": False})
        return rows

    def search(self, words):
        local = self.installed()
        found = []
        for s in self.api("/v2/find?q=" + urllib.parse.quote(" ".join(words))) or []:
            found.append({"name": s["name"], "desc": s.get("summary", ""),
                          "installed": local.get(s["name"], {}).get("version", ""),
                          "classic": s.get("confinement") == "classic"})
        return found

    def info(self, name, width, note):
        local = self.installed().get(name)
        store = (self.api("/v2/find?name=" + urllib.parse.quote(name)) or [None])[0]
        s = local or store
        if not s:
            return [f"  {YELLOW}snap does not know a package called {name}"]
        lines = [k("Package") + f"{BOLD}{TEXT}{name}{RESET}  {DIM}snap"]
        lines.append(k("Installed") + (f"{GREEN}{local.get('version')}{DIM}  rev {local.get('revision')}"
                                        if local else f"{DIM}no"))
        # what the channel you follow has (latest/edge, 6.x/stable…), not the store's default one
        tracked = ((store or {}).get("channels") or {}).get((local or {}).get("tracking-channel") or "", {})
        newest = tracked.get("version") or (store or {}).get("version")
        if store and local and newest and newest != local.get("version"):
            lines.append(k("Available") + f"{YELLOW}{newest}{DIM}  (update pending)")
        elif store and not local:
            lines.append(k("Available") + f"{TEXT}{store.get('version')}")
        if note:
            lines.append(k("Why") + f"{YELLOW}{note}")
        pub = s.get("publisher") or {}
        verified = " ✓" if pub.get("validation") in ("verified", "starred") else ""
        lines.append(k("Publisher") + f"{SUB}{pub.get('display-name', '?')}{GREEN}{verified}")
        channel = (local or {}).get("tracking-channel") or s.get("channel")
        if channel:
            lines.append(k("Channel") + f"{SUB}{channel}")
        conf = s.get("confinement", "")
        lines.append(k("Sandbox") + (f"{YELLOW}{conf}  {DIM}(full access to your system)" if conf == "classic"
                                          else f"{SUB}{conf}"))
        size = (local or {}).get("installed-size") or s.get("download-size")
        if size:
            lines.append(k("Size") + f"{SUB}{human(size)}" + ("" if local else f"{DIM}  download"))
        if s.get("apps"):
            lines.append(k("Commands") + f"{SUB}" + ", ".join(a["name"] if a["name"] == name else f"{name}.{a['name']}"
                                                            for a in s["apps"]))
        for key, label in (("website", "Homepage"), ("contact", "Contact"), ("license", "License")):
            if s.get(key):
                lines.append(k(label) + (f"{BLUE}" if key == "website" else f"{SUB}") + str(s[key]))
        lines += ["", f"  {TEXT}{s.get('summary', '')}", ""] + wrap_lines(s.get("description", ""), width)
        return lines

    def files(self, name):
        root = f"/snap/{name}/current"
        if not os.path.isdir(root):
            return None
        paths = []
        for dirpath, dirs, files in os.walk(root):
            dirs.sort()
            paths.append(dirpath)
            paths += [os.path.join(dirpath, f) for f in sorted(files)]
            if len(paths) > 3000:                 # enough to see what it is
                break
        return paths

    def depends(self, name):
        s = self.installed().get(name)
        if not s:
            s = (self.api("/v2/find?name=" + urllib.parse.quote(name)) or [{}])[0]
        deps = [f"base {s['base']}"] if s.get("base") else []
        conns = self.api("/v2/connections?snap=" + urllib.parse.quote(name)) or {}
        for c in conns.get("established", []):
            if c["plug"]["snap"] == name and c["slot"]["snap"] not in ("snapd", "core", name):
                deps.append(f"{c['slot']['snap']} ({c['interface']})")
        rdeps = sorted({c["plug"]["snap"] for c in conns.get("established", [])
                        if c["slot"]["snap"] == name and c["plug"]["snap"] != name})
        return deps, rdeps

    def install(self, name, row=None):
        return f"sudo snap install {shlex.quote(name)}" + (" --classic" if row and row.get("classic") else "")

    def remove(self, name):
        return f"sudo snap remove {shlex.quote(name)}"

    def upgrade(self, name):
        return f"sudo snap refresh {shlex.quote(name)}"

    def upgrade_all(self):
        return "sudo snap refresh"

    def check(self):
        return "snap refresh --list"

    def checked(self):
        return None


# ═══ Homebrew ═══
class Brew:
    name = "brew"
    sudo = False
    # where Homebrew lives: macOS Apple Silicon, macOS Intel, Linux (looked for again until found:
    # Homebrew installed while the panes run counts from then on)
    PREFIXES = ("/opt/homebrew", "/usr/local", "/home/linuxbrew/.linuxbrew")
    PREFIX = "/home/linuxbrew/.linuxbrew"
    BIN = f"{PREFIX}/bin/brew"
    ENV = {**C_ENV, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ENV_HINTS": "1", "HOMEBREW_NO_INSTALL_CLEANUP": "1",
           "HOMEBREW_NO_COLOR": "1"}
    error = ""
    _catalog = None          # (mtime, {name: (desc, version)}) from the API cache
    _catalog_lock = threading.Lock()
    casks = set()            # installed casks: their commands take --cask

    @classmethod
    def available(cls):
        if not os.access(cls.BIN, os.X_OK):
            found = next((p for p in cls.PREFIXES if os.access(f"{p}/bin/brew", os.X_OK)), None)
            if found:
                cls.PREFIX, cls.BIN = found, f"{found}/bin/brew"
        return os.access(cls.BIN, os.X_OK)

    @staticmethod
    def api_dir():
        """Homebrew's API cache: $HOMEBREW_CACHE, else ~/Library/Caches/Homebrew (macOS) or
        $XDG_CACHE_HOME/Homebrew (Linux)."""
        cache = os.environ.get("HOMEBREW_CACHE")
        if not cache:
            cache = (os.path.expanduser("~/Library/Caches/Homebrew") if sys.platform == "darwin" else
                     os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "Homebrew"))
        return os.path.join(cache, "api")

    def brew(self, *args, timeout=120):
        return run_text(self.BIN, *args, env=self.ENV, timeout=timeout)

    _installed = (0.0, None)

    def installed_json(self, fresh=30):
        """`brew info --json=v2 --installed` (formulae and casks), kept `fresh` seconds ·
        raises when brew does not answer (a pane then keeps what it had)."""
        at, data = Brew._installed
        if data is not None and time.monotonic() - at < fresh:
            return data
        out = self.brew("info", "--json=v2", "--installed")
        try:
            data = json.loads(out)
        except ValueError:
            raise OSError("brew info did not answer")
        Brew.casks = {c.get("token") for c in data.get("casks", [])}
        Brew._installed = (time.monotonic(), data)
        return data

    def mine(self):
        """What you asked for (installed on request), not what came along as a dependency."""
        rows = []
        data = self.installed_json(fresh=0)
        for f in data.get("formulae", []):
            inst = (f.get("installed") or [{}])[0]
            if inst.get("installed_on_request"):
                cellar = os.path.join(self.PREFIX, "Cellar", f["name"], inst.get("version", ""))
                rows.append({"name": f["name"], "version": inst.get("version", ""),
                             "size": dir_size(cellar) if os.path.isdir(cellar) else None, "desc": f.get("desc") or ""})
        for c in data.get("casks", []):           # apps (macOS): always yours, there are no cask dependencies
            rows.append({"name": c.get("token", ""), "version": c.get("installed") or "", "size": None,
                         "desc": c.get("desc") or (c.get("name") or [""])[0], "kind": "cask"})
        return rows

    def updates(self):
        try:
            d = json.loads(self.brew("outdated", "--json=v2"))
        except ValueError:
            raise OSError("brew outdated did not answer")
        Brew.casks |= {c["name"] for c in d.get("casks", [])}
        return [{"name": f["name"], "old": ", ".join(f.get("installed_versions", [])),
                 "new": f.get("current_version", ""), "origin": "pinned" if f.get("pinned") else "homebrew",
                 "security": False, "held": bool(f.get("pinned"))} for f in d.get("formulae", []) + d.get("casks", [])]

    def catalog(self):
        """Every formula with its description and version, from Homebrew's own API cache
        (instant to search). Homebrew 7 keeps it in api/internal/packages.<platform>.jws.json,
        older ones in api/formula.jws.json."""
        api = self.api_dir()
        files = sorted(glob.glob(os.path.join(api, "internal", "packages.*.jws.json"))) or \
            [os.path.join(api, "formula.jws.json")]
        path = files[0]
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        with Brew._catalog_lock:                  # one parse at a time (~130 MB while it runs)
            return self._load_catalog(path, mtime)

    def _load_catalog(self, path, mtime):
        if not Brew._catalog or Brew._catalog[0] != (path, mtime):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                data = json.loads(raw["payload"]) if isinstance(raw, dict) and "payload" in raw else raw
                if isinstance(data, dict):            # internal: {"formulae": {name: {...}}}
                    cat = {n: (i.get("desc") or "", i.get("stable_version", "")) for n, i in data["formulae"].items()}
                else:                                 # older: [{"name": …, "versions": {"stable": …}}]
                    cat = {i["name"]: (i.get("desc") or "", (i.get("versions") or {}).get("stable", "")) for i in data}
                Brew._catalog = ((path, mtime), cat)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                return None
        return Brew._catalog[1]

    def search(self, words):
        try:
            data = self.installed_json()
        except OSError:                       # brew did not answer: search anyway, nothing marked installed
            data = {}
        installed = {f["name"]: (f.get("installed") or [{}])[0].get("version", "") for f in data.get("formulae", [])}
        cat = self.catalog()
        if cat is not None:
            return [{"name": n, "desc": d, "installed": installed.get(n, "")} for n, (d, _) in cat.items()
                    if all(w in f"{n} {d}".lower() for w in words)]
        found = []                       # no API cache yet: brew's own search (slower), on the first
        for line in self.brew("search", "--formula", "--desc", words[0]).splitlines():     # word, then all
            n, sep, d = line.partition(": ")
            if sep and " " not in n and all(w in f"{n} {d}".lower() for w in words):
                found.append({"name": n, "desc": d, "installed": installed.get(n, "")})
        return found

    def info(self, name, width, note):
        try:
            d = json.loads(self.brew("info", "--json=v2", name))
        except ValueError:
            d = {}
        f = (d.get("formulae") or [None])[0]
        if not f and d.get("casks"):
            return self.cask_info(d["casks"][0], width, note)
        if not f:
            return [f"  {YELLOW}Homebrew does not know a formula or cask called {name}"]
        inst = (f.get("installed") or [{}])[0] if f.get("installed") else None
        stable = (f.get("versions") or {}).get("stable", "")
        lines = [k("Package") + f"{BOLD}{TEXT}{name}{RESET}  {DIM}brew"]
        if inst:
            how = "you asked for it" if inst.get("installed_on_request") else "as a dependency"
            lines.append(k("Installed") + f"{GREEN}{inst.get('version')}{DIM}  {how}")
            if f.get("outdated"):                 # brew's own answer (1.2.3_1 is not older than 1.2.3)
                lines.append(k("Available") + f"{YELLOW}{stable}{DIM}  (update pending)")
        else:
            lines.append(k("Installed") + f"{DIM}no")
            lines.append(k("Available") + f"{TEXT}{stable}")
        if note:
            lines.append(k("Why") + f"{YELLOW}{note}")
        if f.get("pinned"):
            lines.append(k("Pinned") + f"{YELLOW}yes · brew upgrade skips it")
        for key, label in (("license", "License"), ("tap", "Tap"), ("homepage", "Homepage")):
            if f.get(key):
                lines.append(k(label) + (f"{BLUE}" if key == "homepage" else f"{SUB}") + str(f[key]))
        cellar = os.path.join(self.PREFIX, "Cellar", name, inst.get("version", "")) if inst else ""
        if cellar and os.path.isdir(cellar):
            lines.append(k("Size") + f"{SUB}{human(dir_size(cellar))}")
        lines += ["", f"  {TEXT}{f.get('desc') or ''}", ""]
        if f.get("caveats"):
            lines += [f"  {BOLD}{BLUE}Caveats{RESET}", ""] + wrap_lines(f["caveats"], width)
        return lines

    def cask_info(self, c, width, note):
        inst = c.get("installed")
        lines = [k("Package") + f"{BOLD}{TEXT}{c.get('token')}{RESET}  {DIM}brew · cask (an app)"]
        lines.append(k("Installed") + (f"{GREEN}{inst}" if inst else f"{DIM}no"))
        if c.get("outdated") or (not inst):
            lines.append(k("Available") + (f"{YELLOW}{c.get('version')}{DIM}  (update pending)" if inst
                                           else f"{TEXT}{c.get('version')}"))
        if note:
            lines.append(k("Why") + f"{YELLOW}{note}")
        for key, label in (("homepage", "Homepage"), ("tap", "Tap")):
            if c.get(key):
                lines.append(k(label) + (f"{BLUE}" if key == "homepage" else f"{SUB}") + str(c[key]))
        names = ", ".join(c.get("name") or [])
        lines += ["", f"  {TEXT}{names}", f"  {SUB}{c.get('desc') or ''}", ""]
        if c.get("caveats"):
            lines += [f"  {BOLD}{BLUE}Caveats{RESET}", ""] + wrap_lines(c["caveats"], width)
        return lines

    def files(self, name):
        out = self.brew("list", "--verbose", name)
        paths = [p for p in out.splitlines() if p.startswith("/")]
        return paths or None

    def depends(self, name):
        try:
            f = (json.loads(self.brew("info", "--json=v2", name)).get("formulae") or [{}])[0]
        except ValueError:
            f = {}
        deps = list(f.get("dependencies") or [])
        rdeps = self.brew("uses", "--installed", name).split()
        return deps, sorted(rdeps)

    def kind(self, name, row=None):
        return " --cask" if (row or {}).get("kind") == "cask" or name in Brew.casks else ""

    def install(self, name, row=None):
        return f"{self.BIN} install{self.kind(name, row)} {shlex.quote(name)}"

    def remove(self, name):
        return f"{self.BIN} uninstall{self.kind(name)} {shlex.quote(name)}"

    def upgrade(self, name):
        return f"{self.BIN} upgrade{self.kind(name)} {shlex.quote(name)}"

    def upgrade_all(self):
        return f"{self.BIN} upgrade"

    def check(self):
        return f"{self.BIN} update"

    def checked(self):
        """When brew last updated: its git (Intel / Linux: PREFIX/Homebrew, Apple Silicon: PREFIX
        itself), else its API cache (Homebrew 4+ updates through the API)."""
        for p in (os.path.join(self.PREFIX, "Homebrew", ".git", "FETCH_HEAD"), os.path.join(self.PREFIX, ".git", "FETCH_HEAD"),
                  self.api_dir()):
            try:
                return os.path.getmtime(p)
            except OSError:
                continue
        return None


SOURCES = {"apt": Apt, "snap": Snap, "brew": Brew}
_live = {}


def sources():
    """The sources there are right now (Homebrew counts from the moment it is installed)."""
    out = []
    for name, cls in SOURCES.items():
        if cls.available():
            out.append(_live.setdefault(name, cls()))
    return out


def source(name):
    cls = SOURCES.get(name)
    return _live.setdefault(name, cls()) if cls and cls.available() else None


# ─── background answers: tmux/background.py (also used by the disk, ssh and git panes) ───
from background import Background  # noqa: E402,F401


# ─── shared by the table panes ───
def how(src, what):
    """The end of a confirmation: what happens next with this source."""
    if src.name == "apt":
        return f" apt shows what it {what} and asks again, with your password"
    return " It asks for your password." if src.sudo else ""


STAMP = "$(python3 -c 'import time; print(time.time_ns())')"     # macOS date has no %N


def pkg_popup(app, title, command):
    """Run a package command in a popup (sudo asks for the password there), say how it went,
    then tell every package pane to re-read."""
    app.popup(title, f"{command}; rc=$?; tmux set -g @pkgs-changed \"{STAMP}\"; "
                     f"if [ $rc -eq 0 ]; then printf '\\n✅ done'; else printf '\\n❌ failed (exit %s)' $rc; fi; "
                     f"printf ' · press Enter'; read -r _", h="60%")


def pkgs_changed(app, stamp):
    """True once after a package command changed something (every package pane sees it).
    stamp: the value of @pkgs-changed, which the panes read on every tick (their `watch`)."""
    if stamp != getattr(app, "_pkgs_seen", None):
        first = not hasattr(app, "_pkgs_seen")
        app._pkgs_seen = stamp
        return not first
    return False


class SourcesPane:
    """Mixin for the package tables (before TableApp): a FROM column, source chips on
    the title row (all · apt · snap · brew, when there is more than one source), slow
    sources answered in the background, and a re-read after any package command."""
    src_filter = "all"
    watch = ("@pkgs-changed", "@pkgs-notes")

    def start_sources(self):
        self.bg = Background(self.wake)

    def keep(self, r):
        return self.src_filter == "all" or r["src"] == self.src_filter

    def chips(self):
        names = [s.name for s in sources()]
        if len(names) < 2 or not self.all:         # nothing to tell apart
            return []
        counts = {}
        for r in self.all:
            counts[r["src"]] = counts.get(r["src"], 0) + 1
        return [("all", "all", self.src_filter == "all")] + \
               [(n, f"{n} {counts.get(n, 0)}", self.src_filter == n) for n in names]

    def on_chip(self, name):
        self.src_filter = name
        self.apply()

    def loading_note(self):
        busy = sorted(self.bg.loading())
        return f"{YELLOW}asking {' · '.join(busy)}…{RESET}" if busy else ""

    def changed(self):
        """After a package command: forget cached answers so everything is asked again ·
        after a note was edited only the notes are read again (no source is asked)."""
        if pkgs_changed(self, self.opts.get("@pkgs-changed")):
            Brew._installed = (0.0, None)
            self.bg.forget()
            return True
        notes = self.opts.get("@pkgs-notes")
        if notes != getattr(self, "_notes_seen", notes):
            self._notes_seen = notes
            return True
        self._notes_seen = notes
        return False


# ─── command line (the `installed-packages` shell function) ───
def installed_version(src, name):
    """Version of name if src has it installed at all (dependencies too), else ''."""
    if src.name == "apt":
        if any(c in name for c in "*?[]"):         # dpkg-query reads those as a pattern
            return ""
        out = run_text("dpkg-query", "-W", "-f", "${Status}\t${Version}\t${binary:Summary}\n", name)
        st, _, rest = (out.splitlines() or [""])[0].partition("\t")
        return rest if st.endswith(" installed") else ""
    if src.name == "snap":
        s = src.installed().get(name)
        return f"{s.get('version', '')}\t{s.get('summary', '')}" if s else ""
    try:
        data = src.installed_json()
    except OSError:
        return ""
    f = next((f for f in data.get("formulae", []) if f["name"] == name), None)
    if f:
        return f"{(f.get('installed') or [{}])[0].get('version', '')}\t{f.get('desc') or ''}"
    c = next((c for c in data.get("casks", []) if c.get("token") == name), None)
    return f"{c.get('installed') or ''}\t{c.get('desc') or ''}" if c else ""


def main(argv):
    clean = lambda t: str(t or "").replace("\t", " ").replace("\n", " ")
    if argv[:1] == ["sources"]:
        print("\n".join(s.name for s in sources()))
    elif argv[:1] == ["mine"]:
        for s in sources():
            if len(argv) > 1 and s.name != argv[1]:
                continue
            try:
                found = s.mine()
            except OSError as e:                   # one source not answering: the others still print
                print(f"{s.name}: {e}", file=sys.stderr)
                continue
            for p in sorted(found, key=lambda p: p["name"]):
                print("\t".join((s.name, p["name"], clean(p.get("version")), clean(p.get("desc")))))
            if s.error:
                print(s.error, file=sys.stderr)
    elif argv[:1] == ["base"]:                  # (re)build ~/.apt-base.txt
        apt = source("apt")
        n = apt.build_base() if apt else None
        if n is None:
            print("❌ No record of the packages the system came with (apt history rotated?)", file=sys.stderr)
            return 1
        print(f"✅ Saved {n} base packages to ~/.apt-base.txt")
    elif argv[:1] == ["find"] and len(argv) == 2:
        found = 0
        for s in sources():
            got = installed_version(s, argv[1])
            if got:
                version, _, desc = got.partition("\t")
                print("\t".join((s.name, argv[1], clean(version), clean(desc))))
                found += 1
        return 0 if found else 1
    else:
        print("usage: pkgsrc.py mine [apt|snap|brew] · find NAME · sources · base", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
