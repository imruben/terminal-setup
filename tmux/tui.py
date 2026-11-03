# ═══════════════════════════════════════════════════════════════
#  Shared bits of the tmux popups (guide.py, sessions.py):
#  Catppuccin colours, a raw full-screen terminal with mouse hover
#  (any-motion tracking), and an input parser that yields events.
# ═══════════════════════════════════════════════════════════════

import os
import re
import select
import signal
import sys
import termios
import tty
import unicodedata


# ─── colours (Catppuccin Mocha) ───
def fg(h): return f"\x1b[38;2;{int(h[1:3], 16)};{int(h[3:5], 16)};{int(h[5:7], 16)}m"
def bg(h): return f"\x1b[48;2;{int(h[1:3], 16)};{int(h[3:5], 16)};{int(h[5:7], 16)}m"


TEXT, SUB, DIM, BLUE = fg("#cdd6f4"), fg("#a6adc8"), fg("#6c7086"), fg("#89b4fa")
ACCENT = BLUE                      # borders, titles, selection: same blue as the tmux bar
GREEN, YELLOW, RED, CRUST = fg("#a6e3a1"), fg("#f9e2af"), fg("#f38ba8"), fg("#11111b")
HOVER, SURFACE, DANGER_BG = bg("#45475a"), bg("#313244"), bg("#f38ba8")
TRACK, THUMB = fg("#313244"), ACCENT
BOLD, RESET, CLEAR_EOL = "\x1b[1m", "\x1b[0m", "\x1b[K"

# Escape sequences take no room on screen: colours and other CSI codes, OSC strings such as
# hyperlinks (\e]8;;url\e\\, which `capture-pane -e` keeps) and charset switches
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>]")


def cw(ch):
    """Cells a character takes: 2 for wide ones (CJK, most emoji), 0 for combining marks
    and zero-width joiners / selectors, 1 for the rest (Nerd Font icons included)."""
    if ch < "\u0300":
        return 1
    if unicodedata.combining(ch) or ch in "\u200b\u200c\u200d\ufe0e\ufe0f" \
            or unicodedata.category(ch) in ("Me", "Mn"):          # (keycaps: 1️⃣ is two cells, not three)
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def vlen(s):
    """Visible width in cells · an emoji made wide by U+FE0F (❤️ ✔️) counts 2, as tmux draws it."""
    t = ANSI.sub("", s)
    if t.isascii():
        return len(t)
    n, prev = 0, 0
    for c in t:
        w = 1 if c == "\ufe0f" and prev == 1 else cw(c)
        n += w
        prev = w if c != "\ufe0f" else 0
    return n


# kept: colours, links, and the two moves the panes draw with on one row (to column N, clear to
# its end): none of them can move to another row
KEEP_CODE = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;[^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[\d*G|\x1b\[K")
COLUMN = re.compile(r"\x1b\[(\d*)G")


def cut(s, n):
    """First n visible cells of s, keeping its colour codes (and links), so no line ever wraps ·
    a tab is one space and other control characters show as ?, so the width is what tmux draws."""
    out, vis, i, full, prev = [], 0, 0, False, 0
    while i < len(s):
        m = ANSI.match(s, i)
        if m:
            if KEEP_CODE.fullmatch(m.group()):
                col = COLUMN.fullmatch(m.group())
                if col:                           # to column N: what follows starts there
                    vis = max(vis, int(col[1] or 1) - 1)
                    if vis >= n:
                        full = True
                        i = m.end()
                        continue
                out.append(m.group())             # other sequences (cursor moves…) are dropped
            i = m.end()
            continue
        if not full:
            ch = s[i]
            if ch == "\t":
                ch = " "
            elif ch < " " or ch == "\x7f":
                ch = "?"
            w = 1 if ch == "\ufe0f" and prev == 1 else cw(ch)
            if vis + w <= n:
                out.append(ch)
                vis += w
                prev = w if ch != "\ufe0f" else 0
            else:
                full = True               # a wide character that does not fit ends the text
        i += 1
    return "".join(out)


def pad(s, n, right=False):
    """s (plain text that fits) padded with spaces to n cells, on the left when right=True."""
    gap = " " * max(0, n - vlen(s))
    return gap + s if right else s + gap


def ellipsis(s, n):
    """Plain text shortened to n cells with a trailing …"""
    return s if vlen(s) <= n else (cut(s, n - 1) + "…" if n > 0 else "")


SGR_CODE = re.compile(r"\x1b\[[0-9;]*m")


def colour_at(tokens):
    """The colour codes in effect after tokens (since the last reset): what a continuation
    line starts with so it keeps the colour."""
    active = []
    for t in tokens:
        if SGR_CODE.fullmatch(t):
            if t in ("\x1b[0m", "\x1b[m"):
                active = []
            else:
                active.append(t)
    return "".join(active)


def wrap(line, width, indent="  "):
    """Split a line (with colour codes) into pieces of `width` visible cells, at a space
    when there is one in the second half of the piece (else mid-word, e.g. a long URL)."""
    width = max(width, len(indent) + 2)       # room for at least one (wide) character
    out, cur, vis, i = [], [], 0, 0          # cur: tokens (colour codes and single characters)
    start = 0                                # cells the current piece began with (its indent)
    while i < len(line):
        m = ANSI.match(line, i)
        if m:
            cur.append(m.group())
            i = m.end()
            continue
        w = 1 if line[i] == "\ufe0f" and i and cw(line[i - 1]) == 1 else cw(line[i])   # ❤️: as vlen counts it
        if vis + w > width and vis > start:
            cut_at, seen = None, 0
            for k, tok in enumerate(cur):            # last space past the middle of the piece
                if not ANSI.fullmatch(tok):
                    seen += vlen(tok)
                    if tok == " " and seen > max(len(indent), width // 2):
                        cut_at = k
            if cut_at is not None and line[i] != " ":
                rest = cur[cut_at + 1:]
                out.append("".join(cur[:cut_at]))
                # the continuation keeps the colour the line had where it was cut
                cur = [indent, colour_at(cur[:cut_at + 1])] + rest
                vis = len(indent) + sum(vlen(t) for t in rest if not ANSI.fullmatch(t))
            else:
                out.append("".join(cur))
                cur, vis = [indent, colour_at(cur)], len(indent)      # continuation lines are indented
                if line[i] == " ":                    # no space at the start of a continuation
                    i += 1
                    continue
            start = len(indent)
        cur.append(line[i])
        vis += w
        i += 1
    out.append("".join(cur))
    return out


def highlight(line, width):
    """Paint a whole row with the hover background (colours inside keep working)."""
    body = cut(line, width)
    return HOVER + body.replace(RESET, RESET + HOVER) + " " * max(0, width - vlen(body)) + RESET


# ─── context menu (looks like tmux's own menus) ───
SELECTED = bg("#89b4fa") + CRUST + BOLD


class Menu:
    """A right-click menu drawn over the screen.

    items: (label, key, action) tuples; action None = disabled; ("", "", None) = separator.
    Taller than the pane: it scrolls (wheel, ▲ ▼ on its border, ↑↓ follow the highlight).
    """

    def __init__(self, title, items, x, y, screen_h, screen_w):
        self.title, self.items = title, items
        # never wider than the pane (long file names, paths): titles and labels are cut to fit
        self.inner = min(max([vlen(title) + 4] + [vlen(l) + len(k) + 5 for l, k, _ in items]), max(12, screen_w - 2))
        self.w = self.inner + 2
        self.rows = max(1, min(len(items), screen_h - 2))      # item rows shown
        self.h = self.rows + 2
        self.off = 0                                           # first item shown
        # open at the pointer, kept fully on screen
        self.x = max(1, min(x, screen_w - self.w + 1))
        self.y = max(1, min(y, screen_h - self.h + 1))
        self.cur = None

    def more_above(self):
        return self.off > 0

    def more_below(self):
        return self.off + self.rows < len(self.items)

    def scroll(self, delta):
        self.off = max(0, min(len(self.items) - self.rows, self.off + delta))

    def show(self, i):
        if i is not None:
            if i < self.off:
                self.off = i
            elif i >= self.off + self.rows:
                self.off = i - self.rows + 1

    def index_at(self, x, y):
        row = y - self.y - 1
        i = row + self.off
        if self.x < x < self.x + self.w - 1 and 0 <= row < self.rows and i < len(self.items) and self.items[i][2]:
            return i
        return None

    def contains(self, x, y):
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def draw(self):
        sys.stdout.write(self.render())
        sys.stdout.flush()

    def render(self):
        """The menu as text to write over the screen."""
        return "".join(f"\x1b[{y};{self.x}H{seg}" for y, seg in self.rows_text().items())

    def rows_text(self):
        """{screen row: the menu's part of it} · Screen.paint puts each one on its row, so a row
        is never on screen without its piece of the menu (no flicker)."""
        border = ACCENT
        t = f" {ellipsis(self.title, self.inner - 2)} "
        left = (self.inner - vlen(t)) // 2
        right = "─" * (self.inner - left - vlen(t))
        if self.more_above():
            right = right[:-4] + f"{RESET}{TEXT} ▲ {RESET}{border}─" if len(right) >= 5 else right
        out = {self.y: f"{border}╭{'─' * left}{BOLD}{t}{RESET}{border}{right}╮{RESET}"}
        for row in range(self.rows):
            n = self.off + row
            label, key, action = self.items[n]
            y = self.y + 1 + row
            if not label:
                out[y] = f"{border}├{'─' * self.inner}┤{RESET}"
                continue
            keytxt = f"({key})" if key else ""
            room = self.inner - len(keytxt) - 1
            text = pad(ellipsis(f" {label}", room), room) + keytxt + " "
            style = SELECTED if n == self.cur else (TEXT if action else DIM)
            out[y] = f"{border}│{RESET}{style}{text}{RESET}{border}│{RESET}"
        bottom = "─" * self.inner
        if self.more_below():
            more = f" ▼ {len(self.items) - self.off - self.rows} more "
            if len(more) + 2 <= self.inner:
                bottom = f"{'─' * (self.inner - len(more) - 1)}{RESET}{TEXT}{more}{RESET}{border}─"
        out[self.y + self.h - 1] = f"{border}╰{bottom}╯{RESET}"
        return out

    def on_mouse(self, b, x, y, released):
        """Returns ('pick', action) · ('close',) · None."""
        if b in (64, 65) and self.contains(x, y):
            self.scroll(-3 if b == 64 else 3)
            self.cur = self.index_at(x, y)
            return None
        if b & 32 or b in (64, 65):
            self.cur = self.index_at(x, y)
            return None
        if b in (0, 2) and not released:
            if not self.contains(x, y):
                return ("close",)
            if y == self.y and self.more_above():              # ▲ on the top border
                self.scroll(-max(1, self.rows - 1))
                return None
            if y == self.y + self.h - 1 and self.more_below():  # ▼ on the bottom border
                self.scroll(max(1, self.rows - 1))
                return None
            i = self.index_at(x, y)
            return ("pick", self.items[i][2]) if i is not None else None
        return None

    def select_first(self):
        """Opened from the keyboard: start on the first item, so Enter works at once."""
        self.cur = next((i for i, it in enumerate(self.items) if it[2]), None)
        self.show(self.cur)
        return self

    def on_key(self, kind, value):
        if kind == "key" and value in ("esc", "ctrl-c"):
            return ("close",)
        enabled = [i for i, it in enumerate(self.items) if it[2]]
        if kind == "key" and value in ("up", "down") and enabled:
            if self.cur not in enabled:
                self.cur = enabled[0 if value == "down" else -1]
            else:
                k = enabled.index(self.cur) + (1 if value == "down" else -1)
                self.cur = enabled[k % len(enabled)]
            self.show(self.cur)
        elif kind == "key" and value in ("pgup", "pgdn", "home", "end") and enabled:
            # the highlight moves too, so Enter picks what is on screen
            if value in ("home", "end"):
                self.cur = enabled[0 if value == "home" else -1]
            else:
                at = self.cur if self.cur in enabled else enabled[0]
                want = at + (self.rows if value == "pgdn" else -self.rows)
                after = [i for i in enabled if i <= want] if value == "pgup" else [i for i in enabled if i >= want]
                self.cur = (after[-1] if value == "pgup" else after[0]) if after else \
                           enabled[0 if value == "pgup" else -1]
            self.show(self.cur)
        elif kind == "key" and value == "enter" and self.cur is not None:
            return ("pick", self.items[self.cur][2])
        elif kind == "char":
            for label, key, action in self.items:
                if action and key == value:
                    return ("pick", action)
        return None


# ─── terminal ───
_painted = {}          # the rows on screen now and its size (Screen.paint writes only what changed)


class Screen:
    """Alternate screen, raw input, mouse with hover. Use as a context manager."""

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        # no autowrap: a line that is wider than measured is cut by the terminal, it never wraps
        # and scrolls the title row away · bracketed paste: pasted text is text, not keys
        Screen.repaint()
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1003h\x1b[?1006h\x1b[?7l\x1b[?2004h")
        sys.stdout.flush()
        # resize (SIGWINCH) and "your tab is in sight again" (SIGUSR1, see tmuxlink.note_wake):
        # the signals only poke a pipe, the event loop handles them
        self.wake_r, wake_w = os.pipe()
        os.set_blocking(wake_w, False)
        def poke(byte):
            try:
                os.write(wake_w, byte)
            except OSError:                       # the pipe is full: a wake is pending anyway
                pass
        signal.signal(signal.SIGWINCH, lambda *_: poke(b"."))
        signal.signal(signal.SIGUSR1, lambda *_: poke(b"v"))
        self.tick = None
        return self

    def __exit__(self, *exc):
        self.restore()
        return False

    def restore(self):
        if self.saved is None:
            return
        Screen.repaint()
        sys.stdout.write("\x1b[?2004l\x1b[?7h\x1b[?1003l\x1b[?1006l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        self.saved = None

    @staticmethod
    def size():
        cols, rows = os.get_terminal_size(sys.stdout.fileno())
        return rows, cols

    @staticmethod
    def paint(lines, over=None):
        """lines: one string per screen row (already cut to width) · never more rows than the
        pane has: one more would scroll the title row away (and mouse rows with it) · over: a
        menu drawn on top. Only the rows that changed since the last paint are written, each
        with its piece of the menu: a redraw (a tick, the pointer moving over the menu) never
        shows a row without the menu, and an unchanged screen writes nothing."""
        rows, cols = Screen.size()
        lines = lines[:max(1, rows)]
        extra = over.rows_text() if over else {}
        x = over.x if over else 1
        frame = {n: l + RESET + CLEAR_EOL for n, l in enumerate(lines, 1)}
        for n, seg in extra.items():                 # the menu's piece goes with its row
            if 1 <= n <= rows:
                frame[n] = frame.get(n, "\x1b[2K") + f"\x1b[{n};{x}H{seg}"
        last = _painted.get("frame") if _painted.get("size") == (rows, cols) else None
        if last is None:
            out = "\x1b[H\x1b[J" + "".join(f"\x1b[{n};1H{f}" for n, f in sorted(frame.items()))
        else:
            out = "".join(f"\x1b[{n};1H{f}" for n, f in sorted(frame.items()) if last.get(n) != f)
            out += "".join(f"\x1b[{n};1H\x1b[2K" for n in sorted(last) if n not in frame)
        _painted.update(size=(rows, cols), frame=frame)
        if out:
            sys.stdout.write(out)
            sys.stdout.flush()

    @staticmethod
    def repaint():
        """The next paint writes every row (the screen was changed behind its back)."""
        _painted.clear()

    def events(self, tick=None):
        """Yield ('resize',) · ('wake',) · ('mouse', button, x, y, released) · ('key', name) ·
        ('char', text) and, when tick (seconds) is given, ('tick',) every time that long passes
        with no input. self.tick can be changed meanwhile (a shorter one applies at once)."""
        import time
        self.tick = tick
        due = None
        while True:
            now = time.monotonic()
            if self.tick and (due is None or due - now > self.tick):
                due = now + self.tick
            elif not self.tick:
                due = None
            wait = max(0.0, due - now) if due else None
            r, _, _ = select.select([self.fd, self.wake_r], [], [], wait)
            if due and time.monotonic() >= due:
                yield ("tick",)
                due = time.monotonic() + (self.tick or 0)    # from the end of the work: never back to back
            if not r:
                continue
            if self.wake_r in r:
                pokes = os.read(self.wake_r, 64)
                if b"v" in pokes:
                    yield ("wake",)
                if b"." in pokes:
                    yield ("resize",)
                if self.fd not in r:
                    continue
            data, self.carry = getattr(self, "carry", b"") + os.read(self.fd, 4096), b""
            # a read can end in the middle of a sequence (fast mouse moves) or of a UTF-8
            # character: give the rest 30 ms, and keep what is still cut off for the next read
            # (an Esc alone after 30 ms is the Esc key)
            t = cut_off(data)
            if t is not None and select.select([self.fd], [], [], 0.03)[0]:
                data += os.read(self.fd, 4096)
                t = cut_off(data)
            if t is not None and data[t:] != b"\x1b":
                data, self.carry = data[:t], data[t:]
            # a paste that has not ended yet (big pastes come in several reads): wait for its end,
            # else the rest would be read as keys (Enter, letters that pick menu items, y…)
            start = data.rfind(b"\x1b[200~")
            if start >= 0 and data.find(b"\x1b[201~", start) < 0 and len(data) - start < 1 << 20:
                self.carry, data = data[start:] + self.carry, data[:start]
            yield from coalesce(parse(data))


MOUSE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
SEQS = {b"\x1b[A": "up", b"\x1bOA": "up", b"\x1b[B": "down", b"\x1bOB": "down",
        b"\x1b[C": "right", b"\x1bOC": "right", b"\x1b[D": "left", b"\x1bOD": "left",
        b"\x1b[5~": "pgup", b"\x1b[6~": "pgdn", b"\x1b[H": "home", b"\x1b[1~": "home",
        b"\x1b[F": "end", b"\x1b[4~": "end", b"\x1b[3~": "delete", b"\x1b[Z": "btab"}
CTRL = {b"\r": "enter", b"\n": "enter", b"\x7f": "backspace", b"\x08": "backspace", b"\t": "tab",
        b"\x1b": "esc", b"\x15": "ctrl-u", b"\x03": "ctrl-c", b"\x04": "ctrl-d", b"\x05": "ctrl-e",
        b"\x0e": "ctrl-n", b"\x12": "ctrl-r", b"\x18": "ctrl-x", b"\x14": "ctrl-t", b"\x13": "ctrl-s"}


CUT_SEQ = re.compile(rb"\x1b(?:\[[0-9;<?]*|O)?")


def cut_off(data):
    """Where an escape sequence or a UTF-8 character cut off by the end of data starts, or None."""
    esc = data.rfind(b"\x1b", max(0, len(data) - 32))
    if esc >= 0 and CUT_SEQ.fullmatch(data, esc):
        return esc
    k, cont = len(data) - 1, 0
    while k >= 0 and cont < 3 and 0x80 <= data[k] < 0xC0:
        k, cont = k - 1, cont + 1
    if k >= 0 and data[k] >= 0xC0 and cont + 1 < (2 if data[k] < 0xE0 else 3 if data[k] < 0xF0 else 4):
        return k
    return None


def coalesce(events):
    """A run of pointer moves read at once (a fast move sends dozens) counts as its last one:
    one redraw, not one per cell crossed."""
    held = None
    for ev in events:
        if ev[0] == "mouse" and ev[1] & 32 and not ev[4]:
            held = ev
            continue
        if held:
            yield held
            held = None
        yield ev
    if held:
        yield held


PASTE = re.compile(rb"\x1b\[200~(.*?)(?:\x1b\[201~|$)", re.S)


def parse(data):
    while data:
        m = PASTE.match(data)
        if m:                            # pasted: plain text (newlines and control keys become spaces)
            text = m[1].decode("utf-8", "replace")
            text = "".join(" " if c < " " or c == "\x7f" else c for c in text).strip()
            if text:
                yield ("char", text)
            data = data[m.end():]
            continue
        m = MOUSE.match(data)
        if m:
            yield ("mouse", int(m[1]), int(m[2]), int(m[3]), m[4] == b"m")
            data = data[m.end():]
            continue
        for seq, name in SEQS.items():
            if data.startswith(seq):
                yield ("key", name)
                data = data[len(seq):]
                break
        else:
            if data.startswith(b"\x1b[") or data.startswith(b"\x1bO"):   # unknown sequence: drop it
                m = re.match(rb"\x1b[\[O][0-9;?]*[ -/]*[@-~]", data)
                data = data[m.end() if m else 2:]
                continue
            ch = data[:1]
            if ch == b"\x1b" and len(data) > 1 and data[1:2] >= b" ":     # Alt+key: not Esc + key
                n = 2
                while n < len(data) and 0x80 <= data[n] < 0xC0:
                    n += 1
                yield ("key", "alt-" + data[1:n].decode("utf-8", "ignore"))
                data = data[n:]
            elif ch in CTRL:
                yield ("key", CTRL[ch])
                data = data[1:]
            elif ch >= b" ":
                n = 1                                   # keep UTF-8 typing intact
                while n < len(data) and 0x80 <= data[n] < 0xC0:
                    n += 1
                yield ("char", data[:n].decode("utf-8", "ignore"))
                data = data[n:]
            else:
                data = data[1:]
