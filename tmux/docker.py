#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Containers pane of the `docker` tab (tmux/system.sh) · like `dps`, live
#  Every container (running first): compose project, state / health, CPU,
#  RAM used / limit, architecture (yellow when emulated), networks, published
#  ports. Title row: totals, emulated containers, restart warnings.
#  The highlighted container drives the Container (details) and Logs panes.
#
#  Double-click a port in PORTS: open it in the browser (elsewhere: the menu).
#  Right-click: logs · shell as you / as root (like `dsh`) · open a port
#  · start / restart / stop / pause / kill / remove · compose project: open its
#  folder, start / restart / stop it · copy name or id. Everything that stops something asks.
# ═══════════════════════════════════════════════════════════════

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tmuxlink
from background import Background
from table import Column, TableApp, run
from tui import DIM, RED, TEXT, YELLOW

ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm", "armv6l": "arm",
        "i686": "386", "i386": "386", "ppc64le": "ppc64le", "s390x": "s390x", "riscv64": "riscv64"}
HOST_ARCH = ARCH.get(platform.machine(), platform.machine())     # until the daemon says (it may be remote)
WEB_IPS = ("", "0.0.0.0", "::", "127.0.0.1", "::1")
ICON = dict(logs="\U000F0331", shell="\U000F018D", root="\U000F0483", web="\U000F059F", start="\U000F040A",
            stop="\U000F04DB", restart="\U000F0450", remove="\U000F0A7A", copy="\U000F018F", folder="\U000F024B",
            pause="\U000F03E4", kill="\U000F0156")


def docker(*args, timeout=10):
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def last_line(out):
    lines = (out or "").strip().splitlines()
    return lines[-1] if lines else "failed"


def short_state(state, status):
    """'Up 3 hours (healthy)' → 'up 3h ✓' · 'Exited (0) 32 hours ago' → 'exited 32h'."""
    m = re.search(r"(\d+|an?|About an?)\s+(second|minute|hour|day|week|month|year)", status)
    age = ""
    if m:
        n = "1" if m[1].lower().startswith(("a", "about")) else m[1]
        age = n + {"second": "s", "minute": "m", "hour": "h", "day": "d", "week": "w", "month": "mo", "year": "y"}[m[2]]
    health = " ✓" if "(healthy)" in status else " ✗" if "(unhealthy)" in status else " …" if "health: starting" in status else ""
    word = {"running": "up", "exited": "exited", "created": "created", "paused": "paused",
            "restarting": "restart", "dead": "dead", "removing": "removing"}.get(state, state)
    code = re.search(r"Exited \((\d+)\)", status)
    if code and code[1] != "0":                          # it failed: say with what
        word = f"exited {code[1]}"
    return f"{word} {age}{health}".strip()


def host_ports(ports, web=False):
    """'0.0.0.0:40525->1025/tcp, [::]:40525->1025/tcp, 6379/tcp' → [40525] · ranges too:
    '0.0.0.0:8000-8002->8000-8002/tcp' → [8000, 8001, 8002] · web=True: only TCP ports that
    localhost reaches (all addresses or loopback), the ones a browser can open."""
    found = set()
    for ip, a, b, proto in re.findall(r"(\[[^\]]*\]|[\d.]*):(\d+)(?:-(\d+))?->[\d-]+/(\w+)", ports or ""):
        if web and (proto != "tcp" or ip.strip("[]") not in WEB_IPS):
            continue
        found.update(range(int(a), int(b or a) + 1))
    return sorted(found)


def mem_bytes(text):
    m = re.match(r"([\d.]+)\s*([KMGT]?i?B)", (text or "").strip())
    if not m:
        return None
    mult = {"B": 1, "KiB": 1024, "kB": 1000, "KB": 1000, "MiB": 1024 ** 2, "MB": 1000 ** 2, "GiB": 1024 ** 3,
            "GB": 1000 ** 3, "TiB": 1024 ** 4}
    return float(m[1]) * mult.get(m[2], 1)


def human(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024


class Stats(threading.Thread):
    """docker stats --no-stream takes ~1 s: keep fresh numbers without blocking the pane.
    Only while the pane is in sight (`wanted`): it is the heaviest thing the monitor runs."""

    def __init__(self):
        super().__init__(daemon=True)
        self.data = {}
        self.wanted = threading.Event()

    def run(self):
        while True:
            self.wanted.wait()
            res = docker("stats", "--no-stream", "--format", "{{json .}}", timeout=20)
            if res and res.returncode == 0:
                data = {}
                for line in res.stdout.splitlines():
                    # a container caught stopping or restarting shows "--": no numbers for it
                    try:
                        s = json.loads(line)
                        cpu = float(s.get("CPUPerc", "0%").rstrip("%") or 0)
                    except ValueError:
                        continue
                    used, _, limit = s.get("MemUsage", "").partition("/")
                    data[s.get("Name")] = (cpu, mem_bytes(used), mem_bytes(limit))
                self.data = data
            time.sleep(3)


class Containers(TableApp):
    icon = "\U000F0868"
    master = True
    title = "Containers"
    noun = "containers"
    interval = 3.0
    sort_key = "order"
    search_keys = ("name", "image", "project", "state_txt", "networks", "ports_txt", "service")
    columns = [Column("name", "CONTAINER", 26, min=14),
               Column("image", "IMAGE"),
               Column("project", "PROJECT", 13, optional=True),
               Column("state_txt", "STATE", 14),
               Column("cpu", "CPU%", 6, "r", desc=True, fmt=lambda v: f"{v:.1f}"),
               Column("mem", "MEM / LIMIT", 14, "r", desc=True, sort="mem_b"),
               Column("arch", "ARCH", 6, optional=True),
               Column("networks", "NETWORKS", 12, optional=True),
               Column("ports_txt", "PORTS", 14)]

    def __init__(self, screen):
        self.stats = Stats()
        self.stats.start()
        self.arch_cache = {}
        self.error = ""
        self.bg = Background(self.wake, fallback=lambda: None)
        super().__init__(screen)
        if self.visible:
            self.stats.wanted.set()

    def read(self):
        """docker ps + inspect, in a thread (a slow or hung daemon must not freeze the pane) ·
        None when docker does not answer, with the reason in self.error."""
        global HOST_ARCH
        # the fields one by one: {{json .}} makes docker work out every container's size each time
        fmt = ('{"ID":{{json .ID}},"Image":{{json .Image}},"Names":{{json .Names}},"State":{{json .State}},'
               '"Status":{{json .Status}},"Ports":{{json .Ports}},"Networks":{{json .Networks}}}')
        res = docker("ps", "-a", "--format", fmt, timeout=8)
        if res is None or res.returncode:
            if res and "permission denied" in res.stderr.lower():
                self.error = "no access to Docker: sudo usermod -aG docker $USER, then open a new login session"
            elif res and "not installed" not in res.stderr and shutil.which("docker"):
                self.error = "Docker is not answering (starting? stopped?): the last list stays meanwhile"
                if getattr(self, "had_rows", False):
                    raise OSError(self.error)          # keep the last rows, ask again in 15 s
            else:
                self.error = "Docker is not running (or not installed): start Docker Desktop / the docker service"
            return {"found": [], "info": {}, "arch": {}}
        self.error = ""
        if not getattr(self, "server_arch", None):          # the daemon's machine, not this client's
            v = docker("version", "-f", "{{.Server.Arch}}", timeout=5)
            if v and v.returncode == 0 and v.stdout.strip():  # (no answer: asked again next time)
                self.server_arch = ARCH.get(v.stdout.strip(), v.stdout.strip())
                HOST_ARCH = self.server_arch
        found = []
        for line in res.stdout.splitlines():
            try:
                found.append(json.loads(line))
            except ValueError:
                pass
        info = {}
        if found:
            # names, restart counts and labels from inspect: ps' "Labels" is one comma-joined
            # string that a value with a comma (a folder) breaks
            ins = docker("inspect", "--format", "{{.Id}}|{{.Name}}|{{.RestartCount}}|{{json .Config.Labels}}",
                         *[c["ID"] for c in found], timeout=8)
            for line in (ins.stdout if ins else "").splitlines():
                cid, name, rc, labels = (line.split("|", 3) + ["", "", "", ""])[:4]
                try:
                    labels = json.loads(labels) or {}
                except ValueError:
                    labels = {}
                info[cid[:12]] = (name.lstrip("/"), int(rc) if rc.isdigit() else 0, labels)
        # the architecture of each image, here in the thread (old daemons have no Platform field)
        arch = {}
        images = sorted({c["Image"] for c in found} - set(self.arch_cache))
        if images:
            ins = docker("image", "inspect", "--format", "{{.Architecture}}", *images, timeout=8)
            got = (ins.stdout.split() if ins else [])
            if len(got) == len(images):
                arch = dict(zip(images, got))
            elif ins is not None:
                # one image gone (or with no Architecture) shifts every answer after it: one by
                # one then, and the ones without an answer are "?" (not asked again every 2.5 s)
                for image in images[:30]:
                    one = docker("image", "inspect", "--format", "{{.Architecture}}", image, timeout=5)
                    arch[image] = (one.stdout.strip() if one and one.returncode == 0 else "") or "?"
        self.arch_cache.update(arch)
        self.had_rows = bool(found)
        return {"found": found, "info": info}

    def image_arch(self, c):
        """The container's platform (docker ps has it since Docker 28), else its image's."""
        plat = c.get("Platform")
        if isinstance(plat, dict) and plat.get("architecture"):
            return plat["architecture"]
        return self.arch_cache.get(c["Image"], "?")        # read in the thread (read())

    def fetch(self):
        got = self.bg.get(("reading",), self.read, 2.5)
        if got is None:
            return self.all                      # the first answer is on its way
        rows = []
        for c in got["found"]:
            name, restarts, labels = got["info"].get(c["ID"][:12], (c["Names"].split(",")[0], 0, {}))
            if labels.get("com.docker.compose.oneoff") == "True":
                project_mate = False             # `compose run`: not one of the project's services
            else:
                project_mate = True
            state = c["State"]
            running = state == "running"
            st = self.stats.data.get(name) if running else None
            hp = host_ports(c.get("Ports"))
            web = host_ports(c.get("Ports"), web=True)
            arch = self.image_arch(c)
            mem = None
            if st and st[1] is not None:
                mem = f"{human(st[1])} / {human(st[2])}" if st[2] else human(st[1])
            project = labels.get("com.docker.compose.project", "")
            rows.append({"id": name, "cid": c["ID"], "name": name, "image": c["Image"], "state": state,
                         "status": c["Status"], "state_txt": short_state(state, c["Status"]), "project": project,
                         "service": labels.get("com.docker.compose.service", ""), "mate": project_mate,
                         "workdir": labels.get("com.docker.compose.project.working_dir", ""),
                         "files": [f for f in labels.get("com.docker.compose.project.config_files", "").split(",") if f],
                         "cpu": st[0] if st else None, "mem": mem, "mem_b": st[1] if st else None,
                         "arch": arch, "emulated": arch not in ("?", "", HOST_ARCH),
                         "networks": c.get("Networks", ""), "restarts": restarts,
                         "ports": hp, "web": web, "ports_txt": " ".join(f":{p}" for p in hp),
                         "order": (not running, project or "~", name)})
        return rows

    # ─── look ───
    def summary(self):
        up = [r for r in self.all if r["state"] == "running"]
        cpu = sum(r["cpu"] or 0 for r in up)
        mem = sum(r["mem_b"] or 0 for r in up)
        parts = [f"{TEXT}{len(up)} up", f"{DIM}CPU {cpu:.1f}%", f"MEM {human(mem)}"]
        emu = sum(1 for r in self.all if r["emulated"])
        if emu:
            parts.append(f"{YELLOW}{emu} emulated{DIM}")
        bad = [f"{r['name']}({r['restarts']})" for r in self.all if r["restarts"]]
        if bad:
            parts.append(f"{RED}⚠ restarts: {', '.join(bad)}{DIM}")
        return f"{DIM} · ".join(parts)

    def row_colour(self, r):
        if "(unhealthy)" in r["status"] or r["state"] == "dead":
            return RED
        if r["state"] == "restarting" or r["emulated"]:
            return YELLOW
        return TEXT if r["state"] == "running" else DIM

    def detail(self, r):
        where = f" · compose {r['project']}/{r['service']}" if r["project"] else ""
        emu = f" · {YELLOW}emulated {r['arch']} on {HOST_ARCH}{DIM}" if r["emulated"] else ""
        return f"{TEXT}{r['image']}{DIM} · {r['status']}{where}{emu}"

    def footer(self, y):
        if self.error and not (self.ask or self.prompt or self.msg):
            return f" {YELLOW}{self.error}"
        return super().footer(y)

    # ─── talking to the other panes ───
    def selected(self, r):
        tmuxlink.put("@docker-selected", r["name"] if r else "")

    watch = ("@docker-focus",)

    def on_tick(self):
        self.stats.wanted.set()                  # in sight: docker stats runs (see Stats)
        want = self.opts.get("@docker-focus")    # "show this container" from the Ports pane
        if want and want != getattr(self, "focus_since", (None,))[0]:
            self.focus_since = (want, time.monotonic())
        if want:
            self.query = ""
            self.reload()
            hit = next((r for r in self.rows if r["name"] == want), None)
            if hit or time.monotonic() - self.focus_since[1] > 10:    # found, or not coming
                tmuxlink.put("@docker-focus", None)
            if hit:
                self.cur_id = self.sel_id = hit["id"]
                self._moved = True               # the detail panes follow it
                self.ensure_visible()

    def dispatch(self, ev):
        super().dispatch(ev)
        if not self.visible:
            self.stats.wanted.clear()            # out of sight: no docker stats for nobody

    # ─── menu ───
    def menu_title(self, r):
        return r["name"]

    def menu_items(self, r):
        state = r["state"]
        up = state == "running"
        alive = state in ("running", "restarting", "paused")      # something docker can stop
        items = [(f"{ICON['logs']}  Logs", "l", lambda: tmuxlink.focus("Logs")),
                 (f"{ICON['shell']}  Shell inside (as you)", "s", (lambda: self.shell(r, root=False)) if up else None),
                 (f"{ICON['root']}  Shell inside (as root)", "S", (lambda: self.shell(r, root=True)) if up else None)]
        for p in r["web"][:3]:
            items.append((f"{ICON['web']}  Open http://localhost:{p}", "o" if p == r["web"][0] else "",
                          lambda p=p: self.browse(p)))
        items += [("", "", None),
                  (f"{ICON['start']}  Start", "a", None if alive else (lambda: self.act(r, "start"))),
                  (f"{ICON['restart']}  Restart…", "r", (lambda: self.ask_act(r, "restart")) if alive else None),
                  (f"{ICON['stop']}  Stop…", "x", (lambda: self.ask_act(r, "stop")) if alive else None),
                  (f"{ICON['pause']}  Unpause", "u", lambda: self.act(r, "unpause")) if state == "paused" else
                  (f"{ICON['pause']}  Pause (freeze its processes)", "u", (lambda: self.act(r, "pause")) if up else None),
                  (f"{ICON['kill']}  Kill · when Stop hangs…", "k", (lambda: self.ask_act(r, "kill")) if alive else None),
                  (f"{ICON['remove']}  Remove…", "d", None if alive else (lambda: self.ask_act(r, "rm")))]
        if r["project"]:
            mates = [x for x in self.all if x["project"] == r["project"] and x["mate"]]
            stopped = sum(1 for x in mates if x["state"] != "running")
            items += [("", "", None),
                      (f"{ICON['folder']}  Open the project folder ({r['project']})", "f",
                       (lambda: self.open_folder(r)) if r["workdir"] and os.path.isdir(r["workdir"]) else None),
                      (f"{ICON['start']}  Start the whole project ({stopped} stopped)", "A",
                       (lambda: self.project(r, "start")) if stopped else None),
                      (f"{ICON['restart']}  Restart the whole project…", "R", lambda: self.ask_project(r, "restart")),
                      (f"{ICON['stop']}  Stop the whole project…", "X",
                       (lambda: self.ask_project(r, "stop")) if stopped < len(mates) else None)]
        items += [("", "", None),
                  (f"{ICON['copy']}  Copy the name", "c", lambda: self.copy(r["name"])),
                  (f"{ICON['copy']}  Copy the id", "i", lambda: self.copy(r["cid"]))]
        return items

    def on_double(self, r, col, x):
        """Double-click a port in PORTS: open that one in the browser · elsewhere: the menu."""
        if col == "ports_txt" and r["web"]:
            x0 = self.col_spans[col][0]
            text, at = r["ports_txt"], x - x0
            word = ""
            if 0 <= at < len(text) and text[at] != " ":          # on a port, not between or after them
                start = text.rfind(" ", 0, at) + 1
                word = text[start:].split(" ", 1)[0].lstrip(":")
            if word.isdigit() and int(word) in r["web"]:
                self.browse(int(word))
                return
        super().on_double(r, col, x)

    def on_delete(self, r):
        self.ask_act(r, "stop" if r["state"] in ("running", "restarting", "paused") else "rm")

    # ─── actions ───
    DOING = {"start": "starting", "stop": "stopping", "restart": "restarting", "kill": "killing",
             "rm": "removing", "pause": "pausing", "unpause": "unpausing"}
    DONE = {"start": "started", "stop": "stopped", "restart": "restarted", "kill": "killed",
            "rm": "removed", "pause": "paused · Unpause brings it back", "unpause": "running again"}

    def ask_act(self, r, verb):
        q = {"stop": f"Stop {r['name']}?",
             "restart": f"Restart {r['name']}?",
             "kill": f"Kill {r['name']} at once (SIGKILL)? it gets no chance to clean up",
             "rm": f"Remove the stopped container {r['name']}? (its image and volumes stay)"}[verb]
        self.confirm(q, lambda: self.act(r, verb), r)

    def act(self, r, verb):
        def done(ok, out):
            self.flash(f"{r['name']}: {self.DONE[verb]}" if ok else f"{r['name']}: {last_line(out)}", ok)
        self.background(r, self.DOING[verb], ["docker", verb, r["cid"]], done)

    def ask_project(self, r, verb):
        n = sum(1 for x in self.all if x["project"] == r["project"] and x["mate"] and x["state"] == "running")
        self.confirm(f"{verb.capitalize()} the whole compose project {r['project']} ({n} running)?",
                     lambda: self.project(r, verb), r)

    def project(self, r, verb):
        def done(ok, out):
            self.flash(f"{r['project']}: {self.DONE[verb]}" if ok else f"{r['project']}: {last_line(out)}", ok)
        # from the project's folder with its own files: compose would otherwise look for a compose
        # file in this pane's folder (and its parents) and act on what it finds there
        files = [a for f in r["files"] if os.path.exists(f) for a in ("-f", f)]
        cwd = r["workdir"] if r["workdir"] and os.path.isdir(r["workdir"]) else "/"
        self.background(r, f"{self.DOING[verb]} project",
                        ["sh", "-c", 'cd "$1" && shift && exec "$@"', "sh", cwd, "docker", "compose", *files,
                         "-p", r["project"], verb], done)

    def shell(self, r, root):
        """A popup with bash (or sh) inside. Images without a shell (distroless, scratch)
        say so in the popup instead of it closing at once."""
        user = "0" if root else f"{os.getuid()}:{os.getgid()}"
        name = shlex.quote(r["name"])
        script = (f"if ! docker exec {name} sh -c true >/dev/null 2>&1; then "
                  f"printf '\\n  This container has no shell (no sh inside the image).\\n"
                  f"  Its logs and details are in the other panes.\\n\\n  press any key to close'; read -rsn1; "
                  f"else exec docker exec -it -u {user} {name} sh -c "
                  f"'if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi'; fi")
        self.popup(f"{'root' if root else 'shell'} · {r['name']} · exit closes", "bash -c " + shlex.quote(script))

    def open_folder(self, r):
        name = tmuxlink.session_for(r["workdir"])
        subprocess.Popen([os.path.join(os.path.dirname(os.path.realpath(__file__)), "terminal.zsh"), "open", name,
                          r["workdir"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.flash(f"session {name} in {r['workdir']}")

    def browse(self, port):
        url = f"{'https' if port in (443, 8443) else 'http'}://localhost:{port}"
        if tmuxlink.open_url(url):
            self.flash(f"opening {url} in the browser")
        else:
            self.flash(f"could not start {tmuxlink.BROWSER}", ok=False)

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash(f"copied: {text}")


if __name__ == "__main__":
    run(Containers)
