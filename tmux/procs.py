#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Processes pane of the `system` session (tmux/system.sh)
#  Reads /proc every 2 s (macOS: ps). CPU% is per core, like top (100% = one full core).
#
#  Right-click a process: stop (SIGTERM) · force kill (SIGKILL), both ask first
#  · show its ports (jumps to the Ports pane) · copy PID / command line.
#  Type to filter (name, user, command) · click a column title to sort.
# ═══════════════════════════════════════════════════════════════

import os
import pwd
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tmuxlink
from table import Column, TableApp, run
from tui import DIM, SUB, TEXT, YELLOW

CLK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
ME = os.getuid()
ICON_STOP, ICON_KILL, ICON_PORTS, ICON_COPY = "\U000F04DB", "\U000F0A7A", "\U000F0318", "\U000F018F"


def human(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024


LINUX = os.path.isdir("/proc/self")       # macOS has no /proc: there ps tells the same


def mem_total():
    if not LINUX:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip()
        return int(out) if out.isdigit() else 1
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    return 1


def ps_processes():
    """macOS: [(pid, ppid, uid, state, rss bytes, cpu%, name, command line)] from ps.
    comm (the program's path) and args may both contain spaces, so they come from two
    calls, each with the spaced field last."""
    env = {**os.environ, "LC_ALL": "C"}           # %cpu as 1.5, not 1,5
    base = subprocess.run(["ps", "-axo", "pid=,ppid=,uid=,stat=,rss=,%cpu=,comm="],
                          capture_output=True, text=True, env=env, timeout=10, stdin=subprocess.DEVNULL).stdout
    args = {}
    for line in subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True, env=env, timeout=10,
                               stdin=subprocess.DEVNULL, errors="replace").stdout.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit():
            args[int(pid)] = cmd.strip()
    out = []
    for line in base.splitlines():
        f = line.split(None, 6)
        if len(f) < 7 or not f[0].isdigit():
            continue
        pid = int(f[0])
        try:
            cpu = float(f[5].replace(",", "."))      # some locales write 1,5
        except ValueError:
            cpu = 0.0
        out.append((pid, int(f[1]), int(f[2]), f[3][:1], int(f[4]) * 1024, cpu,
                    os.path.basename(f[6].strip()), args.get(pid, f[6].strip())))
    return out


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def start_of(pid):
    """When a process started (in ticks since boot, /proc/PID/stat field 22; macOS: ps's
    start time) · None when gone."""
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


class Procs(TableApp):
    icon = "\U000F0430"
    title = "Processes"
    noun = "processes"
    sort_key = "cpu"
    search_keys = ("pid", "user", "name", "cmd")
    columns = [Column("pid", "PID", 7, "r"),
               Column("user", "USER", 9, optional=True),
               Column("cpu", "CPU%", 6, "r", desc=True, fmt=lambda v: f"{v:.1f}"),
               Column("rss", "MEM", 7, "r", desc=True, fmt=human),
               Column("name", "NAME")]

    def __init__(self, screen):
        self.prev = {}
        self.users = {}
        self.total = mem_total()
        out = tmux("display", "-p", "#{pid}").stdout.strip()
        # never offer to kill these: tmux itself, this pane, pid 1 (and 0: kernel_task on macOS)
        self.why_protected = {0: "the kernel", 1: "starts everything else", os.getpid(): "this pane",
                              os.getppid(): "this pane"}
        if out.isdigit():
            self.why_protected[int(out)] = "tmux itself"
        self.protected = set(self.why_protected)
        super().__init__(screen)

    def user(self, uid):
        if uid not in self.users:
            try:
                self.users[uid] = pwd.getpwuid(uid).pw_name
            except KeyError:
                self.users[uid] = str(uid)
        return self.users[uid]

    def fetch(self):
        if not LINUX:
            return [{"id": pid, "pid": pid, "user": self.user(uid), "uid": uid, "cpu": cpu, "rss": rss,
                     "name": name, "cmd": cmd, "state": state, "ppid": ppid}
                    for pid, ppid, uid, state, rss, cpu, name, cmd in ps_processes()]
        now = time.monotonic()
        rows, seen = [], {}
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            pid = int(d)
            try:
                with open(f"/proc/{d}/stat", "rb") as f:          # a name can be any bytes, not UTF-8
                    stat = f.read().decode("utf-8", "replace")
                with open(f"/proc/{d}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
                uid = os.stat(f"/proc/{d}").st_uid
                name = stat[stat.index("(") + 1:stat.rindex(")")]
                f = stat[stat.rindex(")") + 2:].split()
                flags, start = int(f[6]), int(f[19])
                ticks = int(f[11]) + int(f[12])
                rss = int(f[21]) * PAGE
            except (OSError, ValueError, IndexError):            # gone meanwhile, or unreadable
                continue
            if flags & 0x00200000:                               # PF_KTHREAD: a kernel thread
                continue
            if not cmd:                                          # a zombie (it has no command line any more)
                cmd = f"[{name}]"
            elif len(name) == 15:              # the kernel cuts names at 15 chars: use the program
                exe = os.path.basename(cmd.split()[0]) if cmd else ""
                name = exe if exe.startswith(name[:8]) else name
            key = (pid, start)                                   # a pid reused by a new process is new
            seen[key] = (ticks, now)
            p = self.prev.get(key)
            cpu = (ticks - p[0]) / CLK / max(1e-3, now - p[1]) * 100 if p else 0.0
            rows.append({"id": pid, "pid": pid, "user": self.user(uid), "uid": uid, "cpu": max(0.0, cpu),
                         "rss": rss, "name": name, "cmd": cmd, "state": f[0], "ppid": int(f[1]), "start": start})
        self.prev = seen
        return rows

    def row_colour(self, row):
        if row["cpu"] >= 50:
            return YELLOW
        return SUB if row["uid"] == ME else DIM

    def detail(self, r):
        states = {"R": "running", "S": "sleeping", "D": "waiting on disk", "U": "waiting on disk",
                  "Z": "zombie", "T": "stopped", "I": "idle"}
        mem = f"{r['rss'] / self.total * 100:.1f}% of RAM"
        return (f"{TEXT}{r['cmd']}{DIM}  · {states.get(r['state'], r['state'])} · parent {r['ppid']} · {mem}")

    def menu_title(self, r):
        return f"{r['name']} · {r['pid']}"

    def killable(self, r):
        return r["pid"] > 0 and r["pid"] not in self.protected

    def menu_items(self, r):
        k = self.killable(r)
        note = "" if k else f"  ({self.why_protected.get(r['pid'], 'protected')})"
        return [(f"{ICON_STOP}  Stop · SIGTERM…{note}", "s", (lambda: self.ask_kill(r, signal.SIGTERM)) if k else None),
                (f"{ICON_KILL}  Force kill · SIGKILL…{note}", "k", (lambda: self.ask_kill(r, signal.SIGKILL)) if k else None),
                ("", "", None),
                (f"{ICON_PORTS}  Show its ports", "p", lambda: self.show_ports(r)),
                (f"{ICON_COPY}  Copy PID", "c", lambda: self.copy(str(r["pid"]))),
                (f"{ICON_COPY}  Copy command line", "l", lambda: self.copy(r["cmd"]))]

    def on_delete(self, r):
        if self.killable(r):
            self.ask_kill(r, signal.SIGTERM)
        else:
            self.flash(f"{r['name']} is not stopped from here: {self.why_protected.get(r['pid'], 'protected')}", ok=False)

    def ask_kill(self, r, sig):
        if r.get("state") == "Z":                # a zombie has already ended: only its parent can clear it
            self.flash(f"{r['name']} is a zombie: it already ended · its parent ({r['ppid']}) has to reap it", ok=False)
            return
        if sig == signal.SIGKILL:
            q = f"Force kill {r['name']} ({r['pid']})? it cannot clean up, unsaved work is lost"
        else:
            q = f"Stop {r['name']} ({r['pid']})?"
        if r.get("start") is None:               # macOS (ps has no start time in the list): noted now
            r = {**r, "start": start_of(r["pid"])}
        self.confirm(q, lambda: self.kill(r, sig), r)

    def kill(self, r, sig):
        """Only if that pid is still the same process (the question may have stayed open: a pid
        is reused once its process ends) · a stopped process (Ctrl+Z) also gets SIGCONT, or the
        SIGTERM would wait until something resumed it."""
        if start_of(r["pid"]) != r.get("start"):
            self.flash(f"{r['name']} ({r['pid']}) is not running any more: nothing sent")
            self.reload()
            return
        try:
            os.kill(r["pid"], sig)
            if sig == signal.SIGTERM and r.get("state") in ("T", "t"):
                os.kill(r["pid"], signal.SIGCONT)
            self.flash(f"sent {sig.name} to {r['name']} ({r['pid']})")
        except ProcessLookupError:
            self.flash(f"{r['name']} had already finished")
        except PermissionError:
            self.flash(f"{r['name']} belongs to {r['user']}: run  sudo kill -{sig.name[3:]} {r['pid']}", ok=False)
        self.reload()

    def copy(self, text):
        if tmuxlink.copy(text):                     # stdin (no size limit) · pbcopy on macOS too
            self.flash(f"copied: {text[:60]}")
        else:
            self.flash("could not copy: tmux refused it", ok=False)

    def show_ports(self, r):
        tmux("set", "-g", "@ports-query", f"pid={r['pid']}")
        focus("Ports")
        self.flash(f"ports of {r['name']} → Ports pane")


def focus(label):
    """Select the pane of this window whose @label is `label`."""
    out = tmux("list-panes", "-F", "#{pane_id}\t#{@label}").stdout
    for line in out.splitlines():
        pid, _, lab = line.partition("\t")
        if lab == label:
            tmux("select-pane", "-t", pid)


class LinkedProcs(Procs):
    """Takes a filter from the Ports pane (@procs-query) on each refresh."""
    watch = ("@procs-query",)

    def on_tick(self):
        q = (self.opts.get("@procs-query") or "").strip()
        if q:
            tmux("set", "-gu", "@procs-query")
            self.query = q
            self.query_changed()


if __name__ == "__main__":
    run(LinkedProcs)
