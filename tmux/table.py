# ═══════════════════════════════════════════════════════════════
#  Interactive table for the system monitor panes (procs.py, ports.py)
#
#  Mouse: hover highlights · click a column title to sort (again to reverse)
#         · right-click a row for its menu (always with "Copy this row") · wheel scrolls
#         · double-click a row: its main action (on_double; the menu if the pane has none)
#         · 󰊓 zoom on the title row (or double-click the title) · 󰊔 restore
#  Narrow panes: columns shrink to their minimum and optional ones hide, so a row
#  never runs off the right edge.
#         · ✕ after the filter clears it (a filter can come from another pane)
#  Keys:  type to filter · ↑↓ PgUp PgDn Home End move · Enter opens the row menu
#         · ← → sort by the previous / next column · Ctrl+r reverses the order
#         · Tab / Shift+Tab: the next / previous source chip (all · apt · snap · brew)
#         · Del asks to stop it · Esc clears the filter · Ctrl+c quits
#  Rows refresh every few seconds; the highlighted row is followed by its id,
#  and refreshing pauses while a menu or a question is open.
#  Out of sight (another tab or session, nobody attached) a pane does nothing: the rows are
#  first read when it comes into sight, and tmux wakes it then (tmuxlink.note_wake).
# ═══════════════════════════════════════════════════════════════

import os
import subprocess
import sys
import threading
import time

import tmuxlink

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from tui import (ACCENT, BOLD, CLEAR_EOL, CRUST, DANGER_BG, DIM, GREEN, HOVER, RED, RESET, SUB, SURFACE,
                 TEXT, YELLOW, Menu, Screen, bg, cut, ellipsis, highlight, pad, vlen)

ACTIVE_ZOOM = bg("#89b4fa") + CRUST + BOLD

WHEEL_STEP = 3
HIDDEN_CHECK = 30.0  # out of sight: seconds between looks (tmux's hooks wake the pane first: a safety net)
LOOK_EVERY = 2.0     # in sight: seconds between asking tmux about sight, zoom and the options it watches
ICON_ZOOM, ICON_UNZOOM, ICON_COPY, ICON_SELECT = "\U000F0293", "\U000F0294", "\U000F018F", "\U000F0489"
TOP = 3            # first data row on screen (1-based): title, column titles, rows…, footer


class Column:
    def __init__(self, key, title, width=None, align="l", desc=False, fmt=str, sort=None, optional=False, min=None):
        self.key, self.title, self.width, self.align, self.desc, self.fmt = key, title, width, align, desc, fmt
        self.sort = sort or key        # field used to sort (e.g. bytes behind a "245M / 2G" text)
        self.optional = optional       # hidden first when the pane is too narrow
        self.min = min or (min_default(width, title) if width else 12)


def min_default(width, title):
    return max(3, min(width, len(title) + 2))


class TableApp:
    icon = ""
    title = ""
    noun = "rows"
    interval = 2.0
    columns = []
    sort_key = None

    # ─── to override ───
    def fetch(self):
        """→ list of dicts, each with a unique 'id'."""
        return []

    def detail(self, row):
        """Footer text for the highlighted row."""
        return ""

    def menu_items(self, row):
        return []

    def row_colour(self, row):
        return SUB

    def on_double(self, row, col, x):
        """Double-click on a row (col: the column under the pointer). Default: its menu."""
        self.open_menu(row, x, TOP + self.cur_index() - self.top + 1)

    def on_delete(self, row):
        pass

    def order(self, rows):
        """Last word on the order, after the column sort (e.g. groups that always go last)."""
        return rows

    def keep(self, row):
        """False hides the row (a filter of the pane's own, e.g. by source)."""
        return True

    def chips(self):
        """Toggle buttons on the title row: [(name, label, active)] · a click calls on_chip(name)."""
        return []

    def on_chip(self, name):
        pass

    def summary(self):
        """Extra text after the count on the title row (totals…)."""
        return ""

    def empty_menu_items(self):
        """Menu for a right-click where there is no row (e.g. 'check for updates')."""
        return []

    def selected(self, row):
        """Called when the highlighted row changes (row may be None): detail panes follow it."""

    # When True, typing does not filter locally: fetch() reads self.query itself (a search box)
    remote_query = False
    # the fields typing filters on (None: every text or number field of a row, not paths
    # kept for actions, flags or objects; a pane names its own when that matches too much)
    search_keys = None

    # Master of a master/detail layout (Containers → details + logs, package lists → Package):
    # hovering only highlights; the row shown in the detail panes (marked ▌) changes on a
    # click, with the arrows, or after resting the pointer ~0.35 s on a row. So crossing
    # other rows on the way to the detail panes does not change what they show.
    master = False
    DWELL = 0.35
    # ticks come every `interval` seconds of quiet; the rows are fetched again on a tick
    # once `reload_every` seconds went by (0: every tick). A short interval with a long
    # reload_every notices other things (a message from another pane) quickly, cheaply.
    reload_every = 0
    # global tmux options read on every tick, in the same tmux call as the zoom and sight
    # checks: on_tick() finds their values in self.opts
    watch = ()

    def on_tick(self):
        """Every tick while in sight, before the rows are read again (messages from other panes)."""

    # ─── engine ───
    def __init__(self, screen):
        self.screen = screen
        self.query = ""
        self.top = 0
        self.cur_id = None
        self.menu = None
        self.ask = None          # (question, action, row id) waiting for y / n
        self.prompt = None       # [label, text, on_submit] while typing in the footer
        self.busy = {}           # row id → what is running on it in the background
        self.msg = ""
        self.buttons = {}
        self.hover_col = None
        self._last_size = screen.size()
        self.sel_id = None
        self.hover_at = 0.0
        self.touched = False     # the highlight was moved by hand (keys, pointer)
        self.jump = False        # the filter changed: back to the first row
        # sort_key may also be a hidden field (e.g. Docker's running-first order)
        col = next((c for c in self.columns if self.sort_key in (c.key, c.sort)), None)
        if col:
            self.sort_key, self.sort_desc = col.sort, col.desc
        else:
            self.sort_key, self.sort_desc = self.sort_key or self.columns[0].key, False
        self.default_sort = (self.sort_key, self.sort_desc)   # the order the pane starts with (3rd click: back to it)
        # nothing is read until the pane is in sight (the system session starts with every tab)
        self.zoomed, self.visible, self.opts = tmuxlink.pane_view(*self.watch)
        self.all, self.loaded, self.reloaded_at = [], False, float("-inf")
        if self.visible:
            self.reload()
        else:
            self.apply()

    @property
    def frozen(self):
        return bool(self.menu or self.ask or self.prompt)

    def tick_every(self):
        """Seconds between ticks: a master table ticks fast only while a pointer rests on a row that
        is not the selection yet (to notice the dwell), at its interval otherwise."""
        if not self.visible:
            return HIDDEN_CHECK
        if self.master and self.hover_at and self.cur_id != self.sel_id:
            return 0.12
        return self.interval

    def view_state(self):
        """What a pointer move can change on screen: unchanged → no redraw (a move inside one row
        sends dozens of events) · a question or a prompt open: always drawn."""
        m = self.menu
        if self.ask or self.prompt:
            return object()
        return (self.cur_id, self.hover_col, self.top, self.sel_id, self.msg, id(m),
                m and m.cur, m and m.off)

    def reload(self):
        self.reloaded_at = time.monotonic()
        try:
            self.all = self.fetch()
        except Exception as e:                   # keep the last rows and say what went wrong
            self.flash(f"could not read: {type(e).__name__}: {e}", ok=False)
        self.loaded = True
        self.apply()

    def apply(self):
        words = [] if self.remote_query else self.query.lower().split()

        keys = self.search_keys

        def text(r):
            items = ((k, r.get(k)) for k in keys) if keys else r.items()
            return " ".join(str(v) for k, v in items if k != "id" and isinstance(v, (str, int, float))
                            and not isinstance(v, bool)).lower()

        def match(r, w):            # "pid=123" (sent by another pane) is that field exactly
            key, eq, value = w.partition("=")
            if eq and key in r and key != "id":
                return str(r[key]).lower() == value
            return w in text(r)
        rows = [r for r in self.all if self.keep(r) and all(match(r, w) for w in words)]
        # (None last · text and numbers never compared with each other)
        rows.sort(key=lambda r: (r.get(self.sort_key) is None, isinstance(r.get(self.sort_key), str),
                                 r.get(self.sort_key) if r.get(self.sort_key) is not None else 0),
                  reverse=self.sort_desc)
        if self.sort_desc:   # keep empty values last when reversing
            rows.sort(key=lambda r: r.get(self.sort_key) is None)
        self.rows = rows = self.order(rows)
        ids = [r["id"] for r in rows]
        # a new filter starts on its first match; a list nobody moved in stays on its top row
        # (Processes re-sorts every refresh) · a master's selection is kept, the detail panes show it
        if self.cur_id not in ids or self.jump or not (self.touched or self.master):
            self.cur_id = ids[0] if ids else None
        if self.jump and self.master:
            self.sel_id = self.cur_id
        self.jump = False
        if getattr(self, "sel_id", None) not in ids:      # the selection disappeared (filter, removed)
            self.sel_id = self.cur_id

    def query_changed(self):
        """The filter text changed (typed, cleared, or sent by another pane): the row it lands
        on is yours, the panes that follow this one follow it."""
        self.jump, self.top, self.msg = True, 0, ""
        self._moved = True

    def cur_index(self):
        for i, r in enumerate(self.rows):
            if r["id"] == self.cur_id:
                return i
        return None

    def current(self):
        i = self.cur_index()
        return self.rows[i] if i is not None else None

    # ─── geometry ───
    def layout(self):
        self.h, self.w = self.screen.size()
        self.list_h = max(1, self.h - 3)
        self.max_top = max(0, len(self.rows) - self.list_h)
        self.top = min(self.top, self.max_top)
        # responsive columns: hide optional ones (rightmost first), then shrink fixed ones to
        # their minimum, so the row always fits the pane
        avail = self.w - 2
        cols = list(self.columns)
        need = lambda cs: sum((c.width or c.min) + 1 for c in cs)
        for c in reversed(self.columns):
            if need(cols) <= avail:
                break
            if c.optional and c.key != self.sort_key:
                cols.remove(c)
        widths = {c.key: (c.width or 0) for c in cols}
        excess = need(cols) - avail
        for c in sorted([c for c in cols if c.width], key=lambda c: c.width - c.min, reverse=True):
            if excess <= 0:
                break
            cut_by = min(excess, c.width - c.min)
            widths[c.key] -= cut_by
            excess -= cut_by
        flex = [c for c in cols if not c.width]
        rest = max(4, avail - sum(widths[c.key] + 1 for c in cols if c.width) - len(flex))
        for c in flex:
            widths[c.key] = max(4, rest // max(1, len(flex)))
        self.cols_shown, self.widths = cols, widths
        x, self.col_spans = 3, {}
        for c in cols:
            self.col_spans[c.key] = (x, x + self.widths[c.key] - 1)
            x += self.widths[c.key] + 1

    def ensure_visible(self):
        i = self.cur_index()
        if i is None:
            return
        if i < self.top:
            self.top = i
        elif i >= self.top + self.list_h:
            self.top = i - self.list_h + 1

    def cells(self, row):
        out = []
        for c in self.cols_shown:
            v = row.get(c.key)
            t = "" if v is None else c.fmt(v)
            t = ellipsis(t, self.widths[c.key])
            out.append(pad(t, self.widths[c.key], right=c.align == "r"))
        return out

    # ─── drawing ───
    def draw(self):
        self.layout()
        if self.master and self.sel_id is None:
            self.sel_id = self.cur_id
        shown = self.sel_id if self.master else self.cur_id
        # the panes that follow this one change only when you moved here (or on the first draw):
        # a reload that drops the row (uninstalled from another pane) does not take them over
        if shown != getattr(self, "_announced", object()) and (getattr(self, "_moved", True) or shown is not None
                                                               and getattr(self, "_announced", None) is None):
            self._announced = shown
            self._moved = False
            self.selected(next((r for r in self.rows if r["id"] == shown), None))
        self.buttons = {}
        w = self.w
        filt = (f"{DIM}{'search' if self.remote_query else 'filter'} ❯ {RESET}{TEXT}{self.query}{RESET}{YELLOW}▏"
                + (f"{RESET} {SURFACE}{SUB} ✕ {RESET}" if self.query else ""))
        extra = self.summary()
        zb_len = 11
        # title row by priority: title + count + filter + zoom always; the noun, the summary
        # and the hint only when there is room
        chips = self.chips()
        chip_txt = "".join(f" {(ACTIVE_ZOOM if on else SURFACE + SUB)} {label} {RESET}" for _, label, on in chips)
        for parts in ((True, True, True), (True, False, True), (False, False, True), (False, False, False)):
            lead = (f" {ACCENT}{self.icon} {BOLD}{self.title}{RESET}  {DIM}{len(self.rows)}"
                    + (f" {self.noun}" if parts[0] else "") + RESET + " ")
            head = (lead + (chip_txt if parts[2] else "")
                    + (f" {DIM}·{RESET} {extra}{RESET}" if (extra and parts[1]) else "") + f"   {filt}")
            if vlen(head) + zb_len <= w:
                break
        if self.query and vlen(head) + zb_len <= w:     # the ✕ that clears the filter
            self.buttons["clear"] = (1, vlen(head) - 2, vlen(head))
        if chips and parts[2]:                           # where each chip landed, for clicks
            x = vlen(lead) + 1
            for name, label, _ in chips:
                self.buttons[f"chip:{name}"] = (1, x + 1, x + len(label) + 2)
                x += len(label) + 3
        zoomed = getattr(self, "zoomed", False)
        zb = f" {ICON_UNZOOM} restore " if zoomed else f" {ICON_ZOOM} zoom "
        hint = "menu: enter or right-click · sort: ← → or click a title  "
        room = w - vlen(head) - len(zb)
        tail = (RESET + " " * (room - len(hint)) + DIM + hint) if room > len(hint) + 1 else ""
        self.zoom_span = (w - len(zb) + 1, w)
        lines = [cut(head + tail, w - len(zb)) + RESET + CLEAR_EOL + f"\x1b[{w - len(zb) + 1}G"
                 + (ACTIVE_ZOOM if zoomed else SURFACE + SUB) + zb]

        titles = "  "
        for c in self.cols_shown:
            arrow = (" ▼" if self.sort_desc else " ▲") if c.sort == self.sort_key else ""
            t = ellipsis(c.title + arrow, self.widths[c.key])
            t = pad(t, self.widths[c.key], right=c.align == "r")
            style = (ACCENT + BOLD) if c.sort == self.sort_key else (TEXT if c.key == self.hover_col else DIM)
            bgc = HOVER if c.key == self.hover_col else ""
            titles += f"{bgc}{style}{t}{RESET} "
        lines.append(cut(titles, w))

        hot = self.cur_index()
        asking = self.ask[2] if self.ask else None
        for n in range(self.list_h):
            i = self.top + n
            if i >= len(self.rows):
                lines.append("")
                continue
            r = self.rows[i]
            body = "  " + " ".join(self.cells(r))
            if asking is not None and r["id"] == asking:
                lines.append(DANGER_BG + CRUST + pad(cut(body, w), w) + RESET)
            elif self.busy.get(r["id"]):                  # (a worker thread may drop it meanwhile)
                tag = f" {self.busy.get(r['id'], '')}… "
                lines.append(cut(YELLOW + body, w - len(tag)) + RESET + CLEAR_EOL + f"\x1b[{w - len(tag) + 1}G" + YELLOW + tag)
            else:
                if self.master and r["id"] == self.sel_id:     # what the detail panes show
                    body = f"{ACCENT}▌{RESET}" + (TEXT + BOLD if i != hot else TEXT) + body[1:]
                lines.append(highlight(TEXT + body, w) if i == hot else cut(self.row_colour(r) + body, w))

        lines.append(cut(self.footer(self.h), w))
        self.screen.paint(lines, self.menu)

    def footer(self, y):
        if self.prompt:
            label, text, _ = self.prompt
            return (f" {ACCENT}{label} {RESET}{TEXT}{text}{RESET}{YELLOW}▏{RESET}  {DIM}enter save · esc cancel")
        if self.ask:
            q = f" {RED}{BOLD}{ellipsis(self.ask[0], max(10, self.w - 21))}{RESET}  "
            yes, no = f"{DANGER_BG}{CRUST}{BOLD} y  yes {RESET}", f"{SURFACE}{TEXT} n  no {RESET}"
            x = vlen(q) + 1
            self.buttons["yes"] = (y, x, x + 7)
            self.buttons["no"] = (y, x + 10, x + 16)
            return q + yes + "  " + no
        if self.msg:
            return " " + self.msg
        r = self.current()
        waiting = not self.loaded or (not self.all and self.still_loading())
        return " " + (self.detail(r) if r else f"{DIM}{'loading…' if waiting else 'nothing matches'}")

    def still_loading(self):
        """Answers still on their way (a pane with a Background says so): 'loading…', not 'nothing matches'."""
        bg = getattr(self, "bg", None)
        return bool(bg and bg.loading())

    # ─── helpers for subclasses ───
    def confirm(self, question, action, row):
        self.menu, self.ask = None, (question, action, row["id"])

    def flash(self, text, ok=True):
        self.msg = (GREEN if ok else RED) + text
        self.msg_at = time.monotonic()

    def ask_text(self, label, text, on_submit):
        """Type a line in the footer; on_submit(text) on Enter."""
        self.menu, self.prompt = None, [label, text, on_submit]

    def background(self, row, doing, argv, done, timeout=120):
        """Run argv without freezing the pane; done(ok, output) when it finishes (timeout None:
        no limit, for work that may take long, like deleting a big tree). The row shows `doing`."""
        self.busy[row["id"]] = doing

        def work():
            try:
                res = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                     stdin=subprocess.DEVNULL, errors="replace")
                ok, out = res.returncode == 0, (res.stdout + res.stderr).strip()
            except (subprocess.TimeoutExpired, OSError) as e:
                ok, out = False, f"{argv[0]}: {'no answer in time' if isinstance(e, subprocess.TimeoutExpired) else e.strerror}"
            finally:
                self.busy.pop(row["id"], None)
            try:
                done(ok, out)
            except Exception as e:               # a bug in done() must not print over the screen
                self.flash(f"{type(e).__name__}: {e}", ok=False)
            self.wake()
        threading.Thread(target=work, daemon=True).start()

    def wake(self):
        """Ask the event loop to refresh now (used by background work, from any thread): its own
        event, not a resize (which would also ask tmux for the zoom and close a menu)."""
        self.screen.poke(b"r")

    def popup(self, title, command, w="90%", h="80%", env=None):
        """Open a tmux popup over this pane (logs, a shell, apt…) · env: {VAR: value} it gets."""
        extra = [a for k, v in (env or {}).items() for a in ("-e", f"{k}={v}")]
        subprocess.Popen(["tmux", "display-popup", "-E", "-w", w, "-h", h, "-b", "rounded", "-S", "fg=#89b4fa",
                          *extra, "-T", f"#[align=centre,fg=#89b4fa,bold] {title.replace('#', '##')} ", command],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ─── input ───
    def open_menu(self, row, x, y):
        if row:
            self.cur_id = row["id"]
            items = list(self.menu_items(row))
            text = "  ".join(t.strip() for t in self.cells(row) if t.strip())
            items += [("", "", None), (f"{ICON_COPY}  Copy this row", "y", lambda: self.copy_row(text)),
                      (f"{ICON_SELECT}  Select text freely…", "t", tmuxlink.free_select)]
            title = self.menu_title(row)
        else:
            items, title = self.empty_menu_items(), self.title
        if items:
            self.menu = Menu(title, items, x, y, self.h, self.w)

    def copy_row(self, text):
        if tmuxlink.copy(text):
            self.flash("copied the row to the clipboard")
        else:
            self.flash("could not copy: tmux refused it", ok=False)

    def toggle_zoom(self):
        tmuxlink.toggle_zoom()
        self.zoomed = tmuxlink.pane_state("")[0]       # what tmux did (a pane alone in its tab cannot zoom)

    def menu_title(self, row):
        return str(row["id"])

    def hit(self, x, y):
        for name, (row, x0, x1) in self.buttons.items():
            if y == row and x0 <= x <= x1:
                return name
        return None

    def row_at(self, y):
        i = self.top + (y - TOP)
        return self.rows[i] if TOP <= y < TOP + self.list_h and 0 <= i < len(self.rows) else None

    def col_at(self, x, y):
        if y != 2:
            return None
        for key, (x0, x1) in self.col_spans.items():
            if x0 <= x <= x1:
                return key
        return None

    def busy_changed(self):
        """True when this 'resize' was only background work asking for a redraw (with a menu
        or a question open the rows wait: they are read again once it closes)."""
        size = self.screen.size()
        same = size == getattr(self, "_last_size", None)
        self._last_size = size
        # a real resize too: an answer that arrived with it (the two pokes merge) is read now
        if self.visible:
            if self.frozen:
                self._dirty = True
            else:
                self.reload()
        return same

    def dwell(self):
        """Master tables: the pointer rested on a row long enough → it becomes the selection."""
        if (self.master and not self.frozen and self.cur_id != self.sel_id and self.hover_at
                and time.monotonic() - self.hover_at >= self.DWELL):
            self.hover_at = 0.0
            if not tmuxlink.pointer_is_here():           # it left for another pane: keep the selection
                return False
            self.sel_id = self.cur_id
            self._moved = True
            return True
        return False

    def answer(self, yes):
        action = self.ask[1] if self.ask else None
        self.ask = None
        if yes and action:
            action()
        self.catch_up()

    def catch_up(self):
        """Answers that arrived while a menu or question was open: read them now."""
        if getattr(self, "_dirty", False) and not self.frozen:
            self._dirty = False
            self.reload()

    def dispatch(self, ev):
        kind = ev[0]
        if kind in ("key", "char") or (kind == "mouse" and not ev[1] & 32 and ev[1] not in (64, 65)):
            self._moved = True                       # a key or a click: what happens now is yours
        if kind in ("tick", "wake"):
            # tmux is asked on a wake (its tab in sight, a master's selection) or every LOOK_EVERY,
            # not on every tick (a fork each: once a second per pane with a 1 s interval)
            now = time.monotonic()
            if kind == "wake" or not self.visible or now - getattr(self, "_looked", 0.0) >= LOOK_EVERY:
                self._looked = now
                self.zoomed, self.visible, self.opts = tmuxlink.pane_view(*self.watch)
            if not self.visible:                         # out of sight: no work at all
                return
            self.on_tick()
            if not self.frozen:
                if time.monotonic() - self.reloaded_at >= self.reload_every:
                    self.reload()
                if time.monotonic() - getattr(self, "msg_at", 0) > 6:   # messages stay ~6 s
                    self.msg = ""
            return
        if kind == "ready":                              # background work answered: read it
            if self.visible:
                if self.frozen:
                    self._dirty = True                   # (read once the menu or question closes)
                else:
                    self.reload()
            return
        if kind == "resize":
            if not self.busy_changed():                  # a real change of size (zoom / restore too)
                self.zoomed = tmuxlink.pane_state("")[0]
                self.menu = None
            return
        if self.menu:
            res = (self.menu.on_mouse(*ev[1:]) if kind == "mouse" else self.menu.on_key(kind, ev[1]))
            if res:
                self.menu = None
                if res[0] == "pick":
                    res[1]()
                self.catch_up()
            return
        if self.prompt:
            if kind == "char":
                self.prompt[1] += ev[1]
            elif kind == "key" and ev[1] == "backspace":
                self.prompt[1] = self.prompt[1][:-1]
            elif kind == "key" and ev[1] == "ctrl-u":
                self.prompt[1] = ""
            elif kind == "key" and ev[1] in ("esc", "ctrl-c"):
                self.prompt = None
                self.catch_up()
            elif kind == "key" and ev[1] == "enter":
                _, text, submit = self.prompt
                self.prompt = None
                submit(text.strip())
                self.catch_up()
            elif kind == "mouse" and ev[1] in (0, 2) and not ev[4]:
                self.prompt = None                  # clicking away cancels
                self.catch_up()
            return
        if self.ask:
            if kind == "char" and ev[1].lower() in "yn":
                self.answer(ev[1].lower() == "y")
            elif kind == "key" and ev[1] in ("esc", "ctrl-c"):
                self.answer(False)
            elif kind == "mouse" and ev[1] == 0 and not ev[4]:
                self.answer(self.hit(ev[2], ev[3]) == "yes")
            return
        if kind == "mouse":
            self.on_mouse(*ev[1:])
        elif kind == "key":
            self.on_key(ev[1])
        elif kind == "char":
            self.query += ev[1]
            self.query_changed()
            self.reload() if self.remote_query else self.apply()

    def set_query(self, text):
        if text != self.query:
            self.query = text
            self.query_changed()
            self.reload() if self.remote_query else self.apply()
        self.msg = ""

    def sort_by(self, col):
        """Sort by a column (its own direction first) · the same one again reverses · a third
        time: back to the order the pane started with (running first, the config's order…)."""
        if col.sort == self.sort_key and self.sort_desc == col.desc and (col.sort, col.desc) != self.default_sort:
            self.sort_desc = not self.sort_desc
        elif col.sort == self.sort_key and (col.sort, col.desc) != self.default_sort:
            self.sort_key, self.sort_desc = self.default_sort
        elif col.sort == self.sort_key:              # the default column itself: reverse / back
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = col.sort, col.desc
        self.apply()

    def next_chip(self, step):
        chips = self.chips()
        if chips:
            at = next((n for n, (_, _, on) in enumerate(chips) if on), 0)
            self.on_chip(chips[(at + step) % len(chips)][0])

    def on_key(self, name):
        if name == "esc":
            self.set_query("")
        elif name == "backspace":
            self.set_query(self.query[:-1])
        elif name == "ctrl-u":
            self.set_query("")
        elif name in ("ctrl-c", "ctrl-d"):
            raise SystemExit
        elif name in ("up", "down", "pgup", "pgdn", "home", "end"):
            i = self.cur_index() or 0
            step = {"up": -1, "down": 1, "pgup": -self.list_h, "pgdn": self.list_h,
                    "home": -len(self.rows), "end": len(self.rows)}[name]
            if self.rows:
                self.cur_id = self.sel_id = self.rows[max(0, min(len(self.rows) - 1, i + step))]["id"]
                self.touched = True
                self.ensure_visible()
        elif name in ("left", "right"):                  # sort by the previous / next column
            cols = [(c.sort, c.desc) for c in (getattr(self, "cols_shown", None) or self.columns)]
            if self.default_sort[0] not in [k for k, _ in cols]:
                cols.append(self.default_sort)           # the starting order is one more stop
            at = next((n for n, (k, _) in enumerate(cols) if k == self.sort_key), -1)
            self.sort_key, self.sort_desc = cols[(at + (1 if name == "right" else -1)) % len(cols)]
            self.apply()
            self.ensure_visible()
        elif name == "ctrl-r":
            self.sort_desc = not self.sort_desc
            self.apply()
            self.ensure_visible()
        elif name in ("tab", "btab"):
            self.next_chip(1 if name == "tab" else -1)
        elif name == "enter":
            r = self.current()
            i = self.cur_index()
            self.open_menu(r, 4, (TOP + i - self.top + 1) if r is not None else TOP)
            if self.menu:
                self.menu.select_first()
        elif name == "delete":
            r = self.current()
            if r is not None:
                self.on_delete(r)

    def on_mouse(self, b, x, y, released):
        if b in (64, 65):
            self.top = max(0, min(self.max_top, self.top + (-WHEEL_STEP if b == 64 else WHEEL_STEP)))
            b, released = 35, False
        if b & 32:
            tmuxlink.pointer_here()                      # every pane: a master's dwell needs to know it left
            self.hover_col = self.col_at(x, y)
            r = self.row_at(y)
            if r is None:
                self.hover_at = 0.0                      # over the titles / empty space: no dwell
            elif r["id"] != self.cur_id:
                self.cur_id, self.touched = r["id"], True
                self.hover_at = time.monotonic()
                if self.master:
                    tmuxlink.pointer_here(force=True)    # a new row: say so right away
            return
        if released or b not in (0, 2):
            return
        if y == 1 and b == 0 and (self.hit(x, y) or "").startswith("chip:"):
            self.on_chip(self.hit(x, y)[5:])
            return
        if y == 1 and b == 0 and self.hit(x, y) == "clear":
            self.set_query("")
            return
        if y == 1 and b == 0:
            a, z = getattr(self, "zoom_span", (0, -1))
            now = time.monotonic()
            if a <= x <= z or now - getattr(self, "_title_click", 0) < 0.4:   # button or double-click
                self.toggle_zoom()
                self._title_click = 0
            else:
                self._title_click = now
            return
        col = self.col_at(x, y)
        if b == 0 and col:
            self.sort_by(next(c for c in self.columns if c.key == col))
            return
        r = self.row_at(y)
        if r is None:
            if b == 2 and y >= TOP:
                self.open_menu(None, x, y)
            return
        self.cur_id = self.sel_id = r["id"]
        self.touched = True
        if b == 2:
            self.open_menu(r, x, y)
        elif b == 0:                                     # a second click on the same row = double-click
            now = time.monotonic()
            last_id, last_at = getattr(self, "_row_click", (None, 0.0))
            if last_id == r["id"] and now - last_at < 0.4:
                self._row_click = (None, 0.0)
                col = next((k for k, (x0, x1) in self.col_spans.items() if x0 <= x <= x1), None)
                self.on_double(r, col, x)
            else:
                self._row_click = (r["id"], now)


def run(app_class):
    try:
        with Screen() as screen:
            tmuxlink.note_wake()      # first: a wake sent while the pane starts is not lost
            app = app_class(screen)
            app.draw()
            # master tables tick fast to notice a pointer resting on a row (cheap: no fetch);
            # the real refresh still happens every app.interval seconds
            last = time.monotonic()
            for ev in screen.events(tick=app.tick_every()):
                kind = ev[0]
                if kind in ("mouse", "key", "char") and not app.visible:
                    app.dispatch(("wake",))              # input means it is in sight after all
                    last = time.monotonic()
                if kind == "tick" and app.master and app.visible and time.monotonic() - last < app.interval:
                    if app.dwell():
                        app.draw()
                    screen.tick = app.tick_every()          # (the dwell done: back to the slow tick)
                    continue
                motion = kind == "mouse" and ev[1] & 32 and ev[1] not in (64, 65)
                before = app.view_state() if motion else None
                app.dispatch(ev)
                if kind in ("tick", "wake"):
                    last = time.monotonic()          # after the work: a slow fetch is not repeated at once
                screen.tick = app.tick_every()
                if motion and app.view_state() == before:
                    continue                                # the pointer moved, nothing on screen did
                if app.visible or kind not in ("tick", "wake", "ready"):
                    app.draw()
    except SystemExit as e:
        sys.exit(0 if e.code is None else e.code)
    finally:
        tmuxlink.forget_wake()
