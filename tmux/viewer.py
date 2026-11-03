# ═══════════════════════════════════════════════════════════════
#  Read-only pane that shows something about the row highlighted in another
#  pane (Docker details / logs, package details). The other pane publishes its
#  selection in a global tmux option; this pane polls it.
#
#  Mouse: click a tab on top (hover highlights) · wheel scrolls
#         · drag over lines to select them: released → copied to the clipboard
#         · right-click: copy this line / the selection / everything shown
#           / select text freely (tmux copy mode: any characters, only in this pane)
#         · 󰊓 zoom on the title row (or double-click the title) · 󰊔 restore
#  Keys:  Tab / Shift+Tab / ← → switch tab · ↑↓ PgUp PgDn Home End scroll · End follows the end
#         · Enter opens the same menu as a right-click (copy, zoom…) · Esc drops a selection
# ═══════════════════════════════════════════════════════════════

import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tmuxlink
from tui import (ACCENT, ANSI, BOLD, CRUST, DIM, GREEN, HOVER, RESET, SUB, SURFACE, TEXT, THUMB, TRACK, YELLOW,
                 Menu, Screen, bg, cut, ellipsis, vlen, wrap)

ACTIVE_TAB = bg("#89b4fa") + CRUST + BOLD
SELECTED = bg("#585b70")
WHEEL_STEP = 3
TOP = 3            # first content row (1-based): title + tabs, rule, content…
HIDDEN_CHECK = 10.0  # out of sight: seconds between looks (tmux normally wakes the pane first)
ICON_ZOOM, ICON_UNZOOM, ICON_COPY, ICON_SELECT = "\U000F0293", "\U000F0294", "\U000F018F", "\U000F0489"


class Viewer:
    icon = ""
    title = ""
    option = ""            # tmux option holding the key to show (e.g. a container name)
    tabs = []              # tab names; [] = no tabs
    interval = 1.0
    refresh_every = 0      # seconds between reloads of the same key (0 = only when it changes)
    follow_end = False     # stick to the last line (logs) unless you scroll up
    wrap_lines = True      # long lines continue on the next row instead of being cut
    empty = "nothing selected"

    def __init__(self, screen):
        self.screen = screen
        self.tab = 0
        self.key = None
        self.lines = []
        self.src = []          # for every shown row: the index of the line it comes from
        self.top = 0
        self.following = self.follow_end
        self.hover_tab = None
        self.tab_spans = []
        self.loaded_at = 0
        self.zoomed = False
        self.zoom_span = (0, -1)
        self.sel = None        # (first row, last row) selected with the mouse
        self.dragging = None
        self.menu = None
        self.note = ("", 0.0)  # short message on the status row
        self.last_click = (0.0, -1)
        self.poll(force=True)

    # ─── to override ───
    def load(self, key, tab, width):
        """→ list of lines (ANSI colours allowed) for this key and tab."""
        return []

    def status(self):
        """Extra text on the second row (search box, live / paused…)."""
        return ""

    def extra_menu_items(self):
        """More right-click items for a viewer (the Logs pane adds save / time range)."""
        return []

    def source_text(self, index):
        """Plain text of source line `index` (what gets copied)."""
        return ANSI.sub("", self.sources[index]) if index < len(self.sources) else ""

    # global tmux options read with `option` in the same tmux call (their values: self.opts)
    watch = ()

    # ─── engine ───
    def look(self):
        """Zoom, sight and the options this pane follows, in one tmux call · the key to show."""
        self.zoomed, self.visible, self.opts = tmuxlink.pane_view(self.option, *self.watch)
        return self.opts[self.option]

    def poll(self, force=False):
        """Out of sight it does nothing: the key and its contents are read once it is in sight
        (the system session starts with every tab; tmux wakes the pane, see tmuxlink.note_wake)."""
        key = self.look()
        if not self.visible or self.menu:        # a menu open: what it would copy stays as it was
            return
        stale = self.refresh_every and time.monotonic() - self.loaded_at > self.refresh_every
        if force or key != self.key or stale:
            changed = key != self.key
            self.key = key
            self.reload(reset=changed)

    def set_lines(self, sources, width, indent="             "):
        """Show `sources` (one per logical line), wrapping them to the pane."""
        self.sources = sources
        self.lines, self.src = [], []
        for n, line in enumerate(sources):
            pieces = wrap(line, max(10, width - 3), indent=indent) if self.wrap_lines else [line]
            self.lines += pieces
            self.src += [n] * len(pieces)

    def reload(self, reset=False):
        h, w = self.screen.size()
        try:
            sources = self.load(self.key, self.tabs[self.tab] if self.tabs else None, w) if self.key else []
        except OSError as e:     # an unreadable file (root's 0600 compose file…): say so, don't crash
            sources = [f"  {YELLOW}cannot read {e.filename or self.key}: {e.strerror}"]
        except Exception as e:   # anything else: say what, keep the pane alive
            sources = [f"  {YELLOW}could not show this: {type(e).__name__}: {e}"]
        self.set_lines(sources, w)
        self.loaded_at = time.monotonic()
        if reset:
            self.top, self.following, self.sel = 0, self.follow_end, None
        self.clamp()

    def clamp(self):
        h, _ = self.screen.size()
        self.body_h = max(1, h - 2)
        self.max_top = max(0, len(self.lines) - self.body_h)
        if self.following:
            self.top = self.max_top
        self.top = max(0, min(self.top, self.max_top))

    def flash(self, text):
        self.note = (text, time.monotonic())

    def draw(self):
        h, w = self.screen.size()
        self.clamp()
        # title row, responsive: the zoom button always stays; when the rest does not fit
        # the key gets shorter, then the title word goes, then tabs are abbreviated, then the key goes
        zb = f" {ICON_UNZOOM} restore " if self.zoomed else f" {ICON_ZOOM} zoom "
        room = w - len(zb) - 1
        head, self.tab_spans = self.title_row(True, 40, False)
        for title, key_w, short in ((True, 24, False), (False, 24, False), (False, 12, False),
                                    (False, 12, True), (False, 0, True)):
            if vlen(head) <= room:
                break
            head, self.tab_spans = self.title_row(title, key_w, short)
        if room >= 8:
            self.zoom_span = (w - len(zb) + 1, w)
            head = (cut(head, room) + RESET + "\x1b[K" + f"\x1b[{w - len(zb) + 1}G"
                    + (ACTIVE_TAB if self.zoomed else SURFACE + SUB) + zb)
        else:
            self.zoom_span = (0, -1)
        # second row: a fresh message, else what this pane is doing, then a rule
        text, at = self.note
        extra = f"{GREEN}{text}" if text and time.monotonic() - at < 4 else self.status()
        hint = f" menu: enter or right-click{' · tabs: ← →' if len(self.tabs) > 1 else ''} "
        lead = f" {extra}{RESET} " if extra else ""
        fill = w - vlen(lead) - len(hint)
        rule = (lead + DIM + "─" * fill + hint) if fill >= 4 else (lead + DIM + "─" * max(0, w - vlen(lead)))
        lines = [cut(head, w), cut(rule, w)]
        bar = len(self.lines) > self.body_h
        if bar:
            th = max(1, self.body_h * self.body_h // len(self.lines))
            ty = (self.body_h - th) * self.top // max(1, self.max_top)
        text_w = w - (2 if bar else 0)
        for n in range(self.body_h):
            i = self.top + n
            line = self.lines[i] if i < len(self.lines) else ""
            if not self.key and n == 1:
                line = f"  {DIM}{self.empty}"
            if self.sel and self.sel[0] <= i <= self.sel[1] and i < len(self.lines):
                line = SELECTED + cut(line, text_w).replace(RESET, RESET + SELECTED) + " " * max(0, text_w - vlen(cut(line, text_w))) + RESET
            else:
                line = cut(line, text_w)
            if bar:
                line += RESET + "\x1b[K" + f"\x1b[{w}G" + (THUMB + "█" if ty <= n < ty + th else TRACK + "│")
            lines.append(line)
        self.screen.paint(lines)
        if self.menu:
            self.menu.draw()

    @staticmethod
    def short_tab(label):
        """'Warnings 12' → 'War 12', 'Dockerfile' → 'Doc': a short form for narrow panes."""
        word, sep, rest = label.partition(" ")
        return word[:3] + (sep + rest if rest[:1].isdigit() else "")

    def title_row(self, with_title, key_w, short):
        """The title row text and where each tab landed (for clicks)."""
        head = f" {ACCENT}{self.icon}" + (f" {BOLD}{self.title}{RESET}" if with_title else RESET)
        if self.key and key_w:
            head += (f" {DIM}·{RESET} " if with_title else " ") + f"{TEXT}{ellipsis(self.key, key_w)}{RESET}"
        head += "  "
        x, spans = vlen(head) + 1, []
        for n, t in enumerate(self.tabs):
            t = self.short_tab(t) if short else t
            style = ACTIVE_TAB if n == self.tab else (HOVER + TEXT if n == self.hover_tab else SURFACE + SUB)
            head += f"{style} {t} {RESET} "
            spans.append((x, x + len(t) + 1))
            x += len(t) + 3
        return head, spans

    # ─── copying ───
    def copy_rows(self, a, b):
        """Copy the source lines behind rows a..b (each once, unwrapped)."""
        seen, out = set(), []
        for i in range(max(0, a), min(b, len(self.src) - 1) + 1):
            n = self.src[i]
            if n not in seen:
                seen.add(n)
                out.append(self.source_text(n))
        if out:
            if tmuxlink.copy("\n".join(out)):
                self.flash(f"{ICON_COPY} copied {len(out)} line{'s' if len(out) != 1 else ''} to the clipboard")
            else:
                self.flash("could not copy: tmux refused it")

    def row_at(self, y):
        i = self.top + (y - TOP)
        return i if TOP <= y < TOP + self.body_h and 0 <= i < len(self.lines) else None

    def open_menu(self, x, y):
        i = self.row_at(y)
        items = []
        if i is not None:
            items.append((f"{ICON_COPY}  Copy this line", "l", lambda: self.copy_rows(i, i)))
        if self.sel:
            a, b = self.sel
            items.append((f"{ICON_COPY}  Copy the selection", "s", lambda: self.copy_rows(a, b)))
        if self.lines:
            items.append((f"{ICON_COPY}  Copy everything shown", "a", lambda: self.copy_rows(0, len(self.lines) - 1)))
        items.append((f"{ICON_SELECT}  Select text freely…", "t", tmuxlink.free_select))
        items += self.extra_menu_items()
        items += [("", "", None),
                  (f"{ICON_UNZOOM if self.zoomed else ICON_ZOOM}  {'Restore the pane' if self.zoomed else 'Zoom the pane'}",
                   "z", self.toggle_zoom)]
        self.menu = Menu(self.title, items, x, y, *self.screen.size())

    def toggle_zoom(self):
        tmuxlink.toggle_zoom()
        self.zoomed = not self.zoomed

    # ─── input ───
    def scroll(self, delta):
        self.top = max(0, min(self.max_top, self.top + delta))
        self.following = self.follow_end and self.top >= self.max_top

    def switch(self, n):
        if self.tabs:
            self.tab = n % len(self.tabs)
            self.reload(reset=True)

    def on_key(self, name):
        if name in ("tab", "right"):
            self.switch(self.tab + 1)
        elif name in ("btab", "left"):
            self.switch(self.tab - 1)
        elif name in ("up", "down"):
            self.scroll(-1 if name == "up" else 1)
        elif name in ("pgup", "pgdn"):
            self.scroll(-self.body_h if name == "pgup" else self.body_h)
        elif name == "home":
            self.top, self.following = 0, False
        elif name == "end":
            self.top, self.following = self.max_top, self.follow_end
        elif name == "esc":
            self.sel = None
        elif name == "enter":
            self.open_menu(4, TOP)
            self.menu.select_first()
        elif name in ("ctrl-c", "ctrl-d"):
            raise SystemExit

    def on_mouse(self, b, x, y, released):
        if self.menu:
            res = self.menu.on_mouse(b, x, y, released)
            if res:
                self.menu = None
                if res[0] == "pick":
                    res[1]()
            return
        if b in (64, 65):
            self.scroll(-WHEEL_STEP if b == 64 else WHEEL_STEP)
            return
        if getattr(self, "prompt", None) and b in (0, 2) and not released:
            self.prompt = None                       # clicking away cancels a question (like the lists)
            return
        if b & 32:                                   # motion
            tmuxlink.pointer_here()
            self.hover_tab = next((n for n, (a, z) in enumerate(self.tab_spans) if y == 1 and a <= x <= z), None)
            if self.dragging is not None and b & 3 == 0:          # dragging a selection
                if y < TOP:
                    self.scroll(-1)
                elif y >= TOP + self.body_h:
                    self.scroll(1)
                i = self.row_at(min(max(y, TOP), TOP + self.body_h - 1))
                if i is not None:
                    self.sel = (min(self.dragging, i), max(self.dragging, i))
            return
        if b == 0 and released:
            if self.dragging is not None and self.sel and self.sel[0] != self.sel[1]:
                self.copy_rows(*self.sel)
            elif self.dragging is not None:
                self.sel = None                      # a plain click clears the selection
            self.dragging = None
            return
        if b == 2 and not released:
            self.open_menu(x, y)
            return
        if b != 0:
            return
        # left press
        if y == 1:
            a, z = self.zoom_span
            if a <= x <= z:
                self.toggle_zoom()
                return
            for n, (ta, tz) in enumerate(self.tab_spans):
                if ta <= x <= tz:
                    self.switch(n)
                    return
            now = time.monotonic()                   # double-click on the title row: zoom
            if now - self.last_click[0] < 0.4 and self.last_click[1] == 1:
                self.toggle_zoom()
            self.last_click = (now, 1)
            return
        i = self.row_at(y)
        if i is not None:
            self.dragging = i
            self.sel = (i, i)
            if self.follow_end:                      # don't let new lines move what you select
                self.following = False

    def tick(self):
        self.poll()

    def on_char(self, text):
        """Typed text (viewers with a search box use it)."""


class BackgroundViewer(Viewer):
    """A Viewer whose contents are read in a thread (git on a big repo, DNS, ssh…): the pane
    keeps answering while they are read, shows what it had (or 'loading…') meanwhile and
    redraws when they arrive. Subclasses write compute(key, tab, width) instead of load()."""

    def __init__(self, screen):
        from background import Background
        self._ready = False
        self._shown = {}                     # (key, tab) → the last lines shown, while new ones are read
        self._bgv = Background(self._arrived, fallback=lambda: None)
        super().__init__(screen)

    def _arrived(self):
        self._ready = True                   # the next tick (every interval) redraws with them

    def compute(self, key, tab, width):
        return []

    def _compute(self, key, tab, width):
        try:
            return self.compute(key, tab, width)
        except Exception as e:               # say what, keep the pane alive
            return [f"  {YELLOW}could not show this: {type(e).__name__}: {e}"]

    def load(self, key, tab, width):
        k = ("loading", key, tab, width)
        lines = self._bgv.get(k, lambda: self._compute(key, tab, width), self.refresh_every or 30)
        if lines is not None:
            if len(self._shown) > 64:
                self._shown.clear()
                self._bgv.drop()
            self._shown[(key, tab)] = lines
            return lines
        return self._shown.get((key, tab)) or [f"  {DIM}loading…"]

    def tick(self):
        super().tick()
        if self._ready and self.visible:
            self._ready = False
            self.reload()


def run(viewer_class):
    try:
        with Screen() as screen:
            tmuxlink.note_wake()      # first: a wake sent while the viewer starts is not lost
            v = viewer_class(screen)
            v._size = screen.size()
            v.draw()
            for ev in screen.events(tick=v.interval if v.visible else HIDDEN_CHECK):
                if ev[0] in ("mouse", "key", "char") and not v.visible:
                    v.tick()                                # input means it is in sight after all
                if ev[0] in ("tick", "wake"):
                    v.tick()
                    screen.tick = v.interval if v.visible else HIDDEN_CHECK
                    if not v.visible:
                        continue
                elif ev[0] == "mouse":
                    v.on_mouse(*ev[1:])
                elif v.menu and ev[0] in ("key", "char"):
                    res = v.menu.on_key(ev[0], ev[1])
                    if res:
                        v.menu = None
                        if res[0] == "pick":
                            res[1]()
                elif ev[0] == "key":
                    v.on_key(ev[1])
                elif ev[0] == "char":
                    v.on_char(ev[1])
                elif ev[0] == "resize":
                    # background work (a whole-log read, a save) also wakes the pane this way:
                    # only a real change of size closes an open menu
                    size = screen.size()
                    if size != getattr(v, "_size", None):
                        width_changed = size[1] != getattr(v, "_size", (0, 0))[1]
                        v._size, v.menu = size, None
                        if width_changed and v.key:            # wrapped for another width: again
                            v.reload()
                    v.zoomed = tmuxlink.pane_state("")[0]   # zoom / restore resize the pane
                v.draw()
    except SystemExit as e:
        sys.exit(0 if e.code is None else e.code)
    finally:
        tmuxlink.forget_wake()
