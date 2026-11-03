#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Logs pane of the `docker` tab · logs of the highlighted container
#
#  · readable: a coloured level badge, short time, message first; JSON, logfmt,
#    Redis, PostgreSQL… understood (tmux/logfmt.py); HTTP lines as
#    "GET /path → 200 · 12 ms"
#  · tabs All / Warnings / Errors (with counts) · type to search: every word must
#    appear; both look through the WHOLE log of the container, not only the end,
#    and matches are highlighted
#  · live: new lines keep arriving (also into a search) · scroll up to read, it
#    pauses; End follows again · Esc clears the search
#  · times are docker's own (--timestamps) in local time, so every container's
#    lines show your clock, whatever time zone the program inside writes
#  · out of sight (other tab / session, nobody attached) for 5 s the live
#    `docker logs -f` stops; back in sight it goes on from the last line received
#  · drag over lines to copy them (the original lines, e.g. the whole JSON);
#    right-click for copy this line / selection / everything shown · zoom button
#  · right-click → time range (last 15 min / 1 h / 24 h / 7 days / everything):
#    docker itself only sends that part (--since), for searches, tabs and saving
#  · right-click → save the lines shown / the whole log to a file (asks where;
#    asks again before overwriting)
# ═══════════════════════════════════════════════════════════════

import atexit
import collections
import ctypes
import datetime
import os
import re
import signal
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from logfmt import mark, parse
from tui import ANSI, DIM, GREEN, RESET, SUB, SURFACE, TEXT, YELLOW, vlen, wrap
from viewer import Viewer, run

# A log line keeps its colours (SGR: ESC [ digits ; m) and nothing else that a terminal would
# act on: cursor moves, screen clears and resets (ESC c), OSC / DCS / APC strings (also with no
# end), charset switches, C0 and C1 control characters
STRINGS = re.compile(r"\x1b[\]P^_X][^\x07\x1b]*(?:\x07|\x1b\\|$)")
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SGR = re.compile(r"\x1b\[[0-9;]*m")
OTHER = re.compile(r"\x1b[ -/]*[0-~]?|[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f\x80-\x9f]")


def clean(line):
    """A log line with its colours and nothing a terminal would act on."""
    line = STRINGS.sub("", line)                                   # OSC / DCS / APC… (ended or not)
    line = CSI.sub(lambda m: m[0] if SGR.fullmatch(m[0]) else "", line)   # cursor moves, clears…
    out, i = [], 0                                                 # then: any other ESC, C0, C1
    for m in SGR.finditer(line):
        out.append(OTHER.sub("", line[i:m.start()]))
        out.append(m[0])
        i = m.end()
    out.append(OTHER.sub("", line[i:]))
    return "".join(out)


TAIL = 400            # lines shown when nothing filters
SHOW_MAX = 2000       # most matches laid out (the newest; the count covers them all)
FULL_MAX = 100000     # most lines read from a long log (each kept line costs ~1 KB)
LINE_MAX = 8000       # characters of one line shown (the whole line is still what gets copied)
BACK_MAX = 2000       # back in sight after a long time hidden: at most this many lines caught up
SEVERITY = {"All": None, "Warnings": ("warning", "error"), "Errors": ("error",)}
BASE_TABS = ["All", "Warnings", "Errors"]
RANGES = [("Last 15 minutes", "15m"), ("Last hour", "1h"), ("Last 24 hours", "24h"), ("Last 7 days", "168h"),
          ("Everything", None)]
LOG_DIR = os.path.expanduser("~/.tmux/logs")
STOPPED = f"{DIM}── the container stopped writing (exited?) ──{RESET}"
STARTED = f"{DIM}── running again ──{RESET}"
SLEEP_AFTER = 5       # seconds out of sight before the live `docker logs -f` is stopped
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) ?")   # docker logs --timestamps


try:                                    # looked up here: the child (after fork) only calls it
    _PRCTL = ctypes.CDLL(None, use_errno=True).prctl
except (OSError, AttributeError):       # macOS: no prctl
    _PRCTL = None


def die_with_parent():
    """Runs in the child before exec: the kernel ends `docker logs -f` when this pane's program
    goes, however it goes (pane closed, tab rebuilt, killed) · no orphans following logs forever."""
    if _PRCTL:
        _PRCTL(1, 15)                                            # PR_SET_PDEATHSIG, SIGTERM


def stamp_key(ts):
    """Docker trims trailing zeros of the nanoseconds: pad them so stamps compare as text."""
    head, _, frac = ts.rstrip("Z").partition(".")
    return head + "." + frac.ljust(9, "0")
ICON_SAVE, ICON_CLOCK = "\U000F0193", "\U000F0954"


class Logs(Viewer):
    icon = "\U000F0331"
    title = "Logs"
    option = "@docker-selected"
    tabs = BASE_TABS
    interval = 0.4
    follow_end = True
    wrap_lines = False          # this pane wraps by itself
    empty = "highlight a container in the Containers pane"

    def __init__(self, screen):
        self.proc = None
        self.tail = collections.deque(maxlen=TAIL * 4)   # (level, pretty, plain) of the latest lines
        self.full = None                                 # every line, read when a filter needs it
        self.loading = False
        self.counts = collections.Counter()
        self.query = ""
        self.matches = 0
        self.dirty = False
        self.lock = threading.Lock()
        self.gen = 0                                     # bumps when the container changes
        self.since = None                                # time range given to docker (--since)
        self.prompt = None                               # [label, text, on_submit] typed in the status row
        self.gen_full = 0                                # bumps to drop a whole-log read in flight
        self.full_upto = ""                              # stamp of the newest line in the whole-log read
        self.last_stamp = None                           # docker's time of the newest line received
        self.asleep = False                              # live follow stopped while out of sight
        self.hidden_at = None
        self.checked_at = 0.0
        self.started_at = None                           # the container's State.StartedAt when following began
        self.no_logs = ""                                # a logging driver docker logs cannot read
        self.full_proc = None                            # the whole-log read, killed when it is not wanted
        self.new_lines = 0                               # lines that arrived while paused (not shown yet)
        atexit.register(self.stop_all)                   # macOS has no PR_SET_PDEATHSIG: end the children
        for sig in ("SIGTERM", "SIGHUP"):                # killed or the pane closed: atexit runs too
            signal.signal(getattr(signal, sig), lambda *_: sys.exit(0))
        super().__init__(screen)

    def stop_all(self):
        for proc in (self.proc, self.full_proc):
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass

    def state(self, name):
        """(running, started at, logging driver) · (False, None, '') when docker does not answer.
        The driver is 'none' only when docker logs really cannot read it (the none driver, or
        another one with dual logging's cache turned off): since Engine 20.10 it reads them all."""
        try:
            out = subprocess.run(["docker", "container", "inspect", "-f",
                                  "{{.State.Running}}|{{.State.StartedAt}}|{{if eq .HostConfig.LogConfig.Type \"none\"}}none"
                                  "{{else if eq (index .HostConfig.LogConfig.Config \"cache-disabled\") \"true\"}}none"
                                  "{{else}}{{.HostConfig.LogConfig.Type}}{{end}}", name],
                                 capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL).stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            out = ""
        running, _, rest = out.partition("|")
        started, _, driver = rest.partition("|")
        return running == "true", started or None, driver

    # ─── reading ───
    @staticmethod
    def entry(raw):
        """(level, pretty line, lower-case text for searching, original text for copying, docker's
        stamp). Lines come from `docker logs --timestamps`: that stamp is cut off and shown in local time."""
        m = STAMP.match(raw)
        stamp = m[1] if m else None
        line = clean(raw[m.end():] if m else raw).expandtabs(4)        # tabs: Go's zap logs
        plain = ANSI.sub("", line)
        if len(plain) > LINE_MAX:                                      # a 1 MB line: shown cut, copied whole
            line = plain[:LINE_MAX] + f"{RESET}{DIM} … ({len(plain) - LINE_MAX:,} more characters){RESET}"
        lvl, pretty = parse(line, stamp)
        return (lvl, pretty, plain.lower(), plain, stamp)

    def start(self, name):
        self.stop_follow()
        with self.lock:
            if self.full_proc and self.full_proc.poll() is None:
                self.full_proc.kill()                    # the whole log of the container you left
            self.gen += 1
            self.tail.clear()
            self.full, self.loading = None, False
            self.counts = collections.Counter()
            self.last_stamp, self.asleep, self.hidden_at = None, False, None
        self.no_logs, self.new_lines, self.started_at, self.no_docker = "", 0, None, False
        if not name:
            return
        self.follow_from(["--tail", str(TAIL)])
        if self.filtering():
            self.load_full()
        gen = self.gen

        def check():                                   # in a thread: a slow daemon must not freeze the pane
            running, started, driver = self.state(name)
            with self.lock:
                if gen != self.gen:
                    return
                self.started_at = started
                if driver == "none":                   # nothing docker logs can read: stop following
                    self.no_logs = "none (no logs kept)"
            if self.no_logs:
                self.stop_follow()
            self.wake()
        threading.Thread(target=check, daemon=True).start()

    def follow_from(self, where):
        try:
            self.proc = subprocess.Popen(["docker", "logs", "-f", "--timestamps", *where, self.key],
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         preexec_fn=die_with_parent)
        except OSError:                              # no docker any more (Docker Desktop quit on WSL)
            self.proc, self.no_docker = None, True
            return
        threading.Thread(target=self.follow, args=(self.proc, self.gen, self.last_stamp), daemon=True).start()

    def stop_follow(self):
        proc, self.proc = self.proc, None                # the follow thread sees it is not current any more
        if proc:
            proc.kill()
            proc.wait()

    # ─── out of sight: no `docker logs -f` running for nobody ───
    def follow_on(self):
        """Follow again from the newest line received: docker's --since includes that line,
        so lines up to its stamp are skipped. Newer ones also reach a whole-log read."""
        self.follow_from(["--since", self.last_stamp, "--tail", str(BACK_MAX)] if self.last_stamp
                         else ["--tail", str(TAIL)])

    def sight(self, visible):
        now = time.monotonic()
        if not visible:
            if self.hidden_at is None:
                self.hidden_at = now
            elif not self.asleep and self.proc and self.proc.poll() is None and now - self.hidden_at > SLEEP_AFTER:
                self.asleep = True
                self.stop_follow()
            return
        self.hidden_at = None
        if self.asleep:
            self.asleep = False
            self.follow_on()
        elif self.key and not self.no_logs and self.proc and self.proc.poll() is not None and now - self.checked_at > 3:
            # `docker logs -f` ended: go on only once the container really started again (a new
            # StartedAt), else a follow that ends at once would restart forever
            self.checked_at = now
            gen, name = self.gen, self.key

            def check():                                # in a thread, like start()'s
                running, started, _ = self.state(name)
                if running and started and started != self.started_at and gen == self.gen:
                    self.started_at = started
                    with self.lock:
                        self.tail.append((None, STARTED, "", "", None))
                        self.dirty = True
                    self.restart_wanted = True
                    self.wake()
            threading.Thread(target=check, daemon=True).start()
        if getattr(self, "restart_wanted", False):
            self.restart_wanted = False
            self.follow_on()

    def follow(self, proc, gen, after):
        after = stamp_key(after) if after else None
        for raw in iter(proc.stdout.readline, b""):
            try:
                e = self.entry(raw.decode("utf-8", "replace").rstrip("\n"))
            except Exception:                            # a line no format understands: shown as it is
                text = raw.decode("utf-8", "replace").rstrip("\n")
                e = (None, clean(text), text.lower(), text, None)
            if after:
                if e[4] and stamp_key(e[4]) <= after:
                    continue                             # already shown before the pause
                after = None
            with self.lock:
                if gen != self.gen or proc is not self.proc:
                    return
                if e[4]:
                    self.last_stamp = e[4]
                if not self.following:
                    self.new_lines += 1
                self.tail.append(e)
                if self.full is not None and (not e[4] or stamp_key(e[4]) > self.full_upto):
                    if len(self.full) == FULL_MAX:       # kept at FULL_MAX lines: the oldest goes
                        self.counts[self.full[0][0]] -= 1
                    self.full.append(e)                  # a new line after the whole log was read
                    self.counts[e[0]] += 1
                self.dirty = True
        with self.lock:
            if gen == self.gen and proc is self.proc:
                self.tail.append((None, STOPPED, "", "", None))
                self.dirty = True

    def load_full(self):
        """Read the whole log once (in the background) for searches and level tabs."""
        if self.full is not None or self.loading or not self.key:
            return
        self.loading = True
        gen, gen_full, name = self.gen, self.gen_full, self.key

        def work():
            # Popen, so changing container (or range) kills a read no longer wanted
            try:
                proc = subprocess.Popen(["docker", "logs", "--timestamps", "--tail", str(FULL_MAX), *self.since_args(),
                                         name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, preexec_fn=die_with_parent)
            except OSError:
                with self.lock:
                    self.loading = False
                return
            with self.lock:
                if gen != self.gen or gen_full != self.gen_full:     # already not wanted: stop it
                    proc.kill()
                    proc.wait()
                    return
                old = self.full_proc
                self.full_proc = proc
            if old is not None and old.poll() is None and old is not proc:
                old.kill()                                # an older read (another container)
            data, _ = proc.communicate()
            if gen != self.gen or gen_full != self.gen_full:
                return
            lines = data.decode("utf-8", "replace").splitlines()
            self.cut_off = len(lines) >= FULL_MAX

            def safe(l):
                try:
                    return self.entry(l)
                except Exception:
                    return (None, clean(l), l.lower(), l, None)
            # stdout and stderr come one after the other: docker's stamps put them back in order
            entries = sorted((safe(l) for l in lines), key=lambda e: stamp_key(e[4]) if e[4] else "")
            with self.lock:
                if gen == self.gen and gen_full == self.gen_full:
                    # lines arriving live from now on are added if newer than the read
                    self.full_upto = max((stamp_key(e[4]) for e in entries if e[4]), default="")
                    # and those that arrived live after docker finished reading go in now
                    late = [e for e in self.tail if e[4] and stamp_key(e[4]) > self.full_upto]
                    entries += late
                    if late:
                        self.full_upto = stamp_key(late[-1][4])
                    entries = collections.deque(entries, maxlen=FULL_MAX)
                    counts = collections.Counter(e[0] for e in entries)
                    self.full, self.counts, self.loading, self.dirty = entries, counts, False, True
            self.wake()
        threading.Thread(target=work, daemon=True).start()

    def since_args(self):
        return ["--since", self.since] if self.since else []

    def set_range(self, since):
        """A new time range: read the log again for that part."""
        with self.lock:
            self.since, self.full, self.loading = since, None, False
            self.gen += 1                                # drop a full read still running
            if self.full_proc and self.full_proc.poll() is None:
                self.full_proc.kill()
        self.gen_follow_restart()

    def gen_follow_restart(self):
        self.start(self.key)                             # live tail again; full read on demand
        self.top, self.following, self.sel = 0, True, None
        if self.filtering():
            self.load_full()
        self.rebuild()

    def scroll(self, delta):
        super().scroll(delta)
        if self.following:                       # back at the end: show what arrived meanwhile
            self.new_lines = 0
            if self.dirty:
                self.rebuild()

    def wake(self):
        os.kill(os.getpid(), signal.SIGWINCH)

    # ─── what to show ───
    def filtering(self):
        return bool(self.query.strip()) or BASE_TABS[self.tab] != "All" or bool(self.since)

    def rebuild(self):
        _, w = self.screen.size()
        terms = self.query.lower().split()
        wanted = SEVERITY[BASE_TABS[self.tab]]
        with self.lock:
            if self.filtering():
                src = list(self.full) if self.full is not None else []
            else:
                src = list(self.tail)[-TAIL:]
            self.dirty = False
        if self.filtering():
            picked = [e for e in src if (not wanted or e[0] in wanted) and all(t in e[2] for t in terms)]
            self.matches = len(picked)
            src = picked[-SHOW_MAX:]
        width = max(10, w - 3)
        self.entries = src
        self.lines, self.src = [], []
        for n, e in enumerate(src):
            pieces = wrap(mark(e[1], terms), width, indent="      ")
            self.lines += pieces
            self.src += [n] * len(pieces)
        if self.sel and self.sel[1] >= len(self.lines):
            self.sel = None
        self.clamp()

    def source_text(self, index):
        return self.entries[index][3] if index < len(getattr(self, "entries", [])) else ""

    # ─── viewer hooks ───
    def poll(self, force=False):
        key = self.look()
        if self.visible and (force or key != self.key):      # out of sight: nothing is started
            self.key = key
            self.start(key)
            self.top, self.following, self.sel = 0, True, None
            self.rebuild()
        self.sight(self.visible)

    def tick(self):
        self.poll()
        if not self.visible or self.menu:            # a menu is open: its rows stay the ones it was opened on
            return
        # paused (scrolled up): what you read stays where it is · new lines wait for End
        if self.pending:
            self.pending = False
            self.rebuild()
        elif self.dirty and self.following:
            self.rebuild()

    def switch(self, n):
        self.tab = n % len(BASE_TABS)
        if self.filtering():
            self.load_full()
        self.top, self.following, self.new_lines = 0, True, 0
        self.rebuild()

    def draw(self):
        width = self.screen.size()[1]
        self.clear_span = None                       # status() sets it again when the ✕ is drawn
        if (not self.menu and self.dirty and self.following) or width != getattr(self, "_built_w", None):
            self._built_w = width
            self.rebuild()
        # tab labels carry their counts once the whole log has been read
        if self.full is not None:
            self.tabs = ["All", f"Warnings {self.counts['warning']}", f"Errors {self.counts['error']}"]
        else:
            self.tabs = BASE_TABS
        super().draw()

    def status(self):
        if self.prompt:
            label, text, _ = self.prompt
            return f"{YELLOW}{label} {RESET}{TEXT}{text}{RESET}{YELLOW}▏{RESET} {DIM}enter · esc cancels"
        if not self.key:
            return ""
        if getattr(self, "no_docker", False):
            return f"{YELLOW}the docker command is not there (Docker stopped?): pick the container again once it is back"
        if self.no_logs:
            return f"{YELLOW}this container logs to {self.no_logs}: docker logs cannot read it"
        rng = next((l for l, v in RANGES if v == self.since), "")
        search = (f"{YELLOW}{ICON_CLOCK} {rng.lower()}{RESET} {DIM}·{RESET} " if self.since else "") + \
                 f"{DIM}search ❯ {RESET}{TEXT}{self.query}{RESET}{YELLOW}▏{RESET} "
        self.clear_span = None
        if self.query:                               # a ✕ that clears the search, like the lists' filter
            x = 2 + vlen(search)                     # the status row starts at column 2 (Viewer.draw)
            self.clear_span = (x, x + 2)
            search += f"{SURFACE}{SUB} ✕ {RESET} "
        if self.pending:
            state = f"{YELLOW}searching… "
        elif self.filtering():
            if self.full is None:
                state = f"{YELLOW}reading the whole log… "
            else:
                cut = f" (the newest {FULL_MAX:,})" if getattr(self, "cut_off", False) else ""
                state = f"{GREEN}{self.matches} of {len(self.full):,} lines{cut} "
        else:
            new = f" · {self.new_lines} new" if self.new_lines else ""
            state = f"{GREEN}● live " if self.following else f"{YELLOW}⏸ paused{new} · End follows "
        return search + state

    # typing shows at once; the (whole-log) filter runs on the next tick, once you pause
    pending = False

    def on_char(self, text):
        if self.prompt:
            self.prompt[1] += text
            return
        self.query += text
        self.load_full()
        self.top, self.following, self.pending, self.new_lines = 0, True, True, 0

    def on_key(self, name):
        if self.prompt:
            if name == "enter":
                _, text, submit = self.prompt
                self.prompt = None
                submit(text.strip())
            elif name == "esc":
                self.prompt = None
            elif name == "backspace":
                self.prompt[1] = self.prompt[1][:-1]
            elif name == "ctrl-u":
                self.prompt[1] = ""
            return
        if name in ("backspace", "ctrl-u", "esc"):
            if name == "esc" and self.sel:
                self.sel = None                      # Esc: first drop a selection
                return
            if name == "esc" and not self.query:
                self.switch(0)                       # Esc with no search: back to All
                return
            self.query = "" if name != "backspace" else self.query[:-1]
            self.top, self.following, self.pending, self.new_lines = 0, True, True, 0
            return
        super().on_key(name)
        if name == "end":                            # following again: what arrived meanwhile
            self.new_lines = 0
            self.rebuild()
            self.top = self.max_top


    def on_mouse(self, b, x, y, released):
        span = getattr(self, "clear_span", None)
        if b == 0 and not released and y == 2 and span and span[0] <= x <= span[1]:
            self.query, self.top, self.following, self.pending, self.new_lines = "", 0, True, True, 0
            return
        super().on_mouse(b, x, y, released)


class SavingLogs(Logs):
    """Right-click: save to a file (asks where) · time range."""

    def extra_menu_items(self):
        if not self.key:
            return []
        items = [("", "", None),
                 (f"{ICON_SAVE}  Save the lines shown…", "w",
                  (lambda: self.ask_save(whole=False)) if getattr(self, "entries", None) else None),
                 (f"{ICON_SAVE}  Save the whole log{' (this range)' if self.since else ''}…", "W",
                  lambda: self.ask_save(whole=True)),
                 ("", "", None)]
        for n, (label, since) in enumerate(RANGES, 1):
            mark = "●" if since == self.since else "○"
            items.append((f"{mark} {label}", str(n), (lambda s=since: self.set_range(s)) if since != self.since else None))
        return items

    def default_path(self, whole):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        words = re.sub(r"[^\w.-]+", "-", "-".join(self.query.split()))[:30]      # no / in a file name
        what = "" if whole else ("-" + words if self.query.strip() else
                                 "-" + BASE_TABS[self.tab].lower() if BASE_TABS[self.tab] != "All" else "-shown")
        path = os.path.join(LOG_DIR, f"{self.key}-{stamp}{what}.log")
        return "~" + path[len(os.path.expanduser("~")):] if path.startswith(os.path.expanduser("~")) else path

    def ask_save(self, whole):
        self.prompt = ["Save to:", self.default_path(whole), lambda p: self.check_target(p, whole)]

    def check_target(self, path, whole):
        if not path:
            return
        target = os.path.expanduser(path)
        if os.path.isdir(target) or path.endswith("/"):
            target = os.path.join(target, os.path.basename(os.path.expanduser(self.default_path(whole))))
        if os.path.exists(target):
            self.prompt = [f"{os.path.basename(target)} exists · overwrite? y/n:", "",
                           lambda ans: self.save(target, whole) if ans.lower().startswith("y")
                           else self.flash("not saved")]
        else:
            self.save(target, whole)

    def save(self, target, whole):
        try:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        except OSError as e:
            self.flash(f"cannot create the folder: {e.strerror}")
            return
        short = "~" + target[len(os.path.expanduser("~")):] if target.startswith(os.path.expanduser("~")) else target
        if not whole:
            lines = [e[3] for e in self.entries if e[3]]
            try:
                with open(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
                    os.fchmod(f.fileno(), 0o600)              # 600: logs can hold secrets (an old 644 file too)
                    f.write("\n".join(lines) + "\n")
                self.flash(f"{ICON_SAVE} saved {len(lines)} lines to {short}")
            except OSError as e:
                self.flash(f"cannot write {short}: {e.strerror}")
            return
        name, since = self.key, self.since_args()
        self.flash(f"{ICON_SAVE} saving the whole log of {name}…")

        def work():
            try:
                with open(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
                    os.fchmod(f.fileno(), 0o600)
                    res = subprocess.run(["docker", "logs", *since, name], stdout=f, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL)
                with open(target, "rb") as f:
                    n = sum(1 for _ in f)
                self.flash(f"{ICON_SAVE} saved {n} lines to {short}" if res.returncode == 0
                           else f"docker logs failed for {name}")
            except OSError as e:
                self.flash(f"cannot write {short}: {e.strerror}")
            self.wake()
        threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    run(SavingLogs)
