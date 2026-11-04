#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Ports pane of the `system` session (tmux/system.sh)
#  Listening TCP / UDP ports from `ss -tulpnH` (macOS: lsof), refreshed every 2 s.
#
#  Double-click a TCP port: open http://localhost:PORT in the Windows browser.
#  Right-click a port: open it in the browser
#  · copy localhost:PORT · stop / force kill its process (asks first)
#  · show the process (jumps to the Processes pane).
#  Without sudo, ss cannot tell which process owns ports of other users (root):
#  those rows show "?" and say how to deal with them.
# ═══════════════════════════════════════════════════════════════

import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tmuxlink
from table import Column, TableApp, run
from tui import BLUE, DIM, SUB, TEXT

ICON_WEB, ICON_COPY, ICON_STOP, ICON_KILL, ICON_PROC = ("\U000F059F", "\U000F018F", "\U000F04DB",
                                                        "\U000F0A7A", "\U000F0430")
ICON_DOCKER = "\U000F0868"


_docker = [float("-inf"), {}, False]       # when read, the answer, a read running


def docker_ports(on_new=None):
    """{(proto, host port): [(host ip, container name)]} of the published ports (they belong
    to docker-proxy: root, or Docker Desktop's backend) · kept 10 s, read in a thread (docker
    ps takes ~0.1 s, 2 s with a slow daemon: the pane never waits for it), so this returns what
    is known now and on_new() runs when a fresh answer differs."""
    if time.monotonic() - _docker[0] >= 10 and not _docker[2]:
        _docker[2] = True

        def work():
            try:
                found = _read_docker_ports()
                changed = found != _docker[1]
                _docker[0], _docker[1] = time.monotonic(), found
            finally:
                _docker[2] = False
            if changed and on_new:
                on_new()
        threading.Thread(target=work, daemon=True).start()
    return _docker[1]


def _read_docker_ports():
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}|{{.Ports}}"], capture_output=True,
                             text=True, timeout=2, stdin=subprocess.DEVNULL).stdout
    except (subprocess.TimeoutExpired, OSError):
        out = ""
    found = {}
    for line in out.splitlines():
        name, _, ports = line.partition("|")
        # 0.0.0.0:8000-8002->8000-8002/tcp · [::]:53->53/udp · 127.0.0.2:8080->80/tcp
        for ip, a, b, proto in re.findall(r"(\[[^\]]*\]|[\d.]*):(\d+)(?:-(\d+))?->[\d-]+/(\w+)", ports):
            for port in range(int(a), int(b or a) + 1):
                found.setdefault((proto, port), []).append((ip.strip("[]"), name))
    return found


def container_for(dock, proto, addr, port):
    """The container that publishes this socket: the one on its exact IP, else on all of them."""
    owners = dock.get((proto, port), [])
    ip = addr.strip("[]").split("%")[0]
    exact = [n for i, n in owners if i == ip]
    # all IPs of the same family: a program of yours on [::1]:8080 is not the container on 0.0.0.0:8080
    v6 = ":" in ip
    anyip = [n for i, n in owners if i == "" or ip in ("*", "") or (i == "::" if v6 else i == "0.0.0.0")]
    return (exact or anyip or [None])[0]


def start_of(pid):
    """When a process started (/proc/PID/stat field 22; macOS: ps's start time) · None when gone."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            stat = f.read().decode("utf-8", "replace")
        return int(stat[stat.rindex(")") + 2:].split()[19])
    except FileNotFoundError:
        if os.path.isdir("/proc/self"):
            return None                          # Linux: the process is gone
    except (OSError, ValueError, IndexError):
        return None
    # no /proc (macOS): ps's start time, to the second ("Tue Nov  4 10:12:33 2026")
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=3, stdin=subprocess.DEVNULL).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return None
    return out or None


def state_of(pid):
    """R, S, T (stopped)… · macOS (no /proc): what ps says."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            stat = f.read().decode("utf-8", "replace")
        return stat[stat.rindex(")") + 2:].split()[0]
    except (OSError, ValueError, IndexError):
        pass
    try:
        return subprocess.run(["ps", "-o", "state=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=3).stdout.strip()[:1]
    except (subprocess.TimeoutExpired, OSError):
        return ""
HAS_PROC = os.path.isdir("/proc/self")
PROC = re.compile(r'\("([^"]+)",pid=(\d+)')


def sockets():
    """Listening sockets as (proto, "addr:port", pid or None, program or "?").
    Linux: ss · macOS: lsof (without sudo it sees your own programs only, like ss)."""
    if shutil.which("ss"):
        try:
            out = subprocess.run(["ss", "-tulpnH"], capture_output=True, text=True, timeout=5,
                                 stdin=subprocess.DEVNULL, errors="replace").stdout
        except (subprocess.TimeoutExpired, OSError):
            return
        for line in out.splitlines():
            parts = line.split(None, 6)
            if len(parts) < 5:
                continue
            # several processes can share the socket (nginx, gunicorn, php-fpm: the master and its
            # workers), in no set order: the lowest pid is the master, which stopping a worker would not stop
            ms = PROC.findall(parts[6]) if len(parts) > 6 else []
            m = min(ms, key=lambda x: int(x[1])) if ms else None
            yield parts[0], parts[4], (int(m[1]) if m else None), (m[0] if m else "?")
        return
    # two calls: lsof's TCP state filter would also drop every UDP socket
    out = ""
    for sel in (["-iTCP", "-sTCP:LISTEN"], ["-iUDP"]):
        try:
            out += subprocess.run(["lsof", "-nP", *sel, "-F", "pcPn"], capture_output=True, text=True, timeout=8,
                                  stdin=subprocess.DEVNULL, errors="replace").stdout
        except (subprocess.TimeoutExpired, OSError):
            pass
    pid, cmd, proto = None, "?", ""
    for line in out.splitlines():
        tag, val = line[:1], line[1:]
        if tag == "p":
            pid, cmd = int(val), "?"
        elif tag == "c":
            cmd = val
        elif tag == "P":
            proto = val.lower()
        elif tag == "n" and "->" not in val:        # UDP: only bound sockets, not connections
            yield proto, val, pid, cmd


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def where(addr):
    a = addr.split("%")[0].strip("[]")          # [fe80::1]%eth0 → fe80::1
    if a in ("0.0.0.0", "::", "*"):
        return "everyone"
    if a in ("127.0.0.1", "::1", "localhost") or a.startswith("127."):
        return "this machine"
    return a


class Ports(TableApp):
    icon = "\U000F0318"
    title = "Ports"
    noun = "listening"
    sort_key = "port"
    search_keys = ("port", "proto", "where", "addr", "pid", "name")
    columns = [Column("port", "PORT", 6, "r"),
               Column("proto", "PROTO", 5, optional=True),
               Column("where", "OPEN TO", 15, min=8),
               Column("pid", "PID", 7, "r", optional=True),
               Column("name", "PROCESS")]

    def fetch(self):
        dock = docker_ports(self.wake)
        rows, seen = [], set()
        for proto, local, pid, name in sockets():
            addr, _, port = local.rpartition(":")
            if not port.isdigit():
                continue
            container = container_for(dock, proto, addr, int(port))
            if container:
                name = f"docker:{container}"
            key = (proto, port, where(addr), pid)      # 127.0.0.53 and 127.0.0.54 are the same to you
            if key in seen:
                continue
            seen.add(key)
            # the pid is part of the id: two programs can listen on one port (SO_REUSEPORT)
            rows.append({"id": f"{proto}|{addr}|{port}|{pid}", "port": int(port), "proto": proto, "addr": addr,
                         "where": where(addr), "pid": pid, "name": name, "container": container,
                         "start": start_of(pid) if pid and HAS_PROC else None})   # (macOS: at the question)
        return rows

    def order(self, rows):
        # your own programs and containers first; system ports you cannot touch go to the bottom
        return sorted(rows, key=lambda r: r["pid"] is None and not r["container"])

    def row_colour(self, r):
        if r["container"]:
            return BLUE
        if r["pid"] is None:
            return DIM
        return TEXT if r["where"] == "everyone" else SUB

    def detail(self, r):
        if r["container"]:
            return (f"{TEXT}container {r['container']}{DIM} publishes {r['addr']}:{r['port']}"
                    f"  · http://localhost:{r['port']} · right-click → Show the container")
        if r["pid"] is None:
            return (f"{DIM}{r['proto']} {r['addr']}:{r['port']} · owned by another user (root):"
                    f" see it with  sudo {'ss -tulpn' if shutil.which('ss') else 'lsof -nP -i'} | grep :{r['port']}")
        url = f"  · http://localhost:{r['port']}" if r["proto"] == "tcp" else ""
        return f"{TEXT}{r['name']}{DIM} (pid {r['pid']}) on {r['addr']}:{r['port']}{url}"

    def menu_title(self, r):
        return f":{r['port']} · {r['name']}"

    def menu_items(self, r):
        has = r["pid"] is not None
        tcp = r["proto"] == "tcp"
        if r["container"]:
            c = r["container"]
            return [(f"{ICON_WEB}  Open http://localhost:{r['port']}", "o", lambda: self.browse(r)),
                    (f"{ICON_COPY}  Copy localhost:{r['port']}", "c", lambda: self.copy(f"localhost:{r['port']}")),
                    ("", "", None),
                    (f"{ICON_DOCKER}  Show the container", "p", lambda: self.show_container(c)),
                    (f"{ICON_STOP}  Stop the container…", "s", lambda: self.ask_stop_container(r))]
        return [(f"{ICON_WEB}  Open http://localhost:{r['port']}", "o", (lambda: self.browse(r)) if tcp else None),
                (f"{ICON_COPY}  Copy localhost:{r['port']}", "c", lambda: self.copy(f"localhost:{r['port']}")),
                ("", "", None),
                (f"{ICON_STOP}  Stop {r['name']} · SIGTERM…", "s", (lambda: self.ask_kill(r, signal.SIGTERM)) if has else None),
                (f"{ICON_KILL}  Force kill · SIGKILL…", "k", (lambda: self.ask_kill(r, signal.SIGKILL)) if has else None),
                (f"{ICON_PROC}  Show the process", "p", (lambda: self.show_proc(r)) if has else None)]

    def on_double(self, r, col, x):
        if r["proto"] == "tcp":
            self.browse(r)
        else:
            self.flash(f"udp :{r['port']} is not a web page · right-click for more", ok=False)

    def show_container(self, name):
        tmuxlink.put("@docker-focus", name)
        tmuxlink.focus("Containers")
        self.flash(f"{name} → docker tab")

    def on_delete(self, r):
        """A container's port: stop the container (its owner is Docker's proxy or backend, whose
        end would take every container with it) · else the program, when it is yours to stop."""
        if r["container"]:
            self.ask_stop_container(r)
        elif r["pid"] is not None:
            self.ask_kill(r, signal.SIGTERM)
        else:
            self.flash(f":{r['port']} belongs to another user (root): not stopped from here", ok=False)

    def ask_stop_container(self, r):
        c = r["container"]
        self.confirm(f"Stop the container {c}, which publishes :{r['port']}?",
                     lambda: self.background(r, "stopping", ["docker", "stop", c],
                                             lambda ok, out: self.flash(f"{c}: stopped" if ok else out, ok)), r)

    def ask_kill(self, r, sig):
        what = f"{r['name']} ({r['pid']}), which listens on :{r['port']}"
        q = (f"Force kill {what}? unsaved work is lost" if sig == signal.SIGKILL else f"Stop {what}?")
        if r.get("start") is None:               # macOS: noted now, checked when you answer
            r = {**r, "start": start_of(r["pid"])}
        self.confirm(q, lambda: self.kill(r, sig), r)

    def kill(self, r, sig):
        """Only if that pid is still the same program (a pid is reused once its process ends) ·
        a stopped one (Ctrl+Z) also gets SIGCONT, or the SIGTERM would wait."""
        if start_of(r["pid"]) != r.get("start"):
            self.flash(f"{r['name']} ({r['pid']}) is not running any more: nothing sent")
            self.reload()
            return
        try:
            os.kill(r["pid"], sig)
            if sig == signal.SIGTERM and state_of(r["pid"]) in ("T", "t"):
                os.kill(r["pid"], signal.SIGCONT)
            self.flash(f"sent {sig.name} to {r['name']} ({r['pid']}) · port :{r['port']}")
        except ProcessLookupError:
            self.flash(f"{r['name']} had already finished")
        except PermissionError:
            self.flash(f"not yours: run  sudo kill -{sig.name[3:]} {r['pid']}", ok=False)
        self.reload()

    def browse(self, r):
        scheme = "https" if r["port"] in (443, 8443) else "http"
        url = f"{scheme}://localhost:{r['port']}"
        if tmuxlink.open_url(url):
            self.flash(f"opening {url} in the browser")
        else:
            self.flash(f"could not start {tmuxlink.BROWSER}", ok=False)

    def copy(self, text):
        if tmuxlink.copy(text):                     # stdin (no size limit) · pbcopy on macOS too
            self.flash(f"copied: {text[:60]}")
        else:
            self.flash("could not copy: tmux refused it", ok=False)

    def show_proc(self, r):
        tmux("set", "-g", "@procs-query", f"pid={r['pid']}")
        out = tmux("list-panes", "-F", "#{pane_id}\t#{@label}").stdout
        for line in out.splitlines():
            pane, _, lab = line.partition("\t")
            if lab == "Processes":
                tmux("select-pane", "-t", pane)
        self.flash(f"{r['name']} → Processes pane")

    watch = ("@ports-query",)

    def on_tick(self):               # a filter sent from the Processes pane
        q = (self.opts.get("@ports-query") or "").strip()
        if q:
            tmux("set", "-gu", "@ports-query")
            self.query = q
            self.query_changed()


if __name__ == "__main__":
    run(Ports)
