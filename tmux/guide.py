#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  tmux guide · Shortcuts / Mouse / Terminal
#  Opened by tmux/guide.zsh (Ctrl+a ? / Ctrl+a g / `terminal guide` / `keys`).
#  Arguments start it with that search typed in (`keys git`).
#
#  Mouse: click a tab on top · hover highlights · click runs it · wheel scrolls
#         · drag or click the scrollbar on the right
#  Keys:  Tab / ← → switch tab · type to search (all tabs) · ↑↓ PgUp PgDn move
#         · Enter runs · Esc clears / closes
#
#  The entries live in tmux/guide.zsh (GUIDE block).
# ═══════════════════════════════════════════════════════════════

import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tmuxlink
from tui import (ACCENT, BOLD, CLEAR_EOL, CRUST, DIM, GREEN, HOVER, RESET, SUB, SURFACE, TEXT, THUMB,
                 TRACK, YELLOW, Screen, bg, cut, ellipsis, highlight, vlen)

GUIDE_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guide.zsh")
KEYS_W = 32
WHEEL_STEP = 3
TOP = 4            # first list row on screen (1-based): tabs, subtitle, rule, list…, footer
ICON_HELP, ICON_SEARCH, ICON_RUN = "\U000F02D6", "\U000F0349", "\U000F040A"
TAB_ICONS = {"Shortcuts": "\U000F030C", "Mouse": "\U000F037D", "Terminal": "\U000F018D"}
ACTIVE_TAB = bg("#89b4fa") + CRUST + BOLD
CHIP = bg("#313244") + TEXT          # a key drawn as a key
CHIP_HOT = bg("#585b70") + TEXT


def load():
    """Tabs: [(title, subtitle, rows)]; rows: ('head', title, sub) · ('item', keys, desc, cmd, group)."""
    text = open(GUIDE_FILE, encoding="utf-8").read()
    body = text.split("GUIDE=$(cat <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
    tabs, group = [], ""
    for line in body.splitlines():
        keys, desc, cmd = (line.split("|", 2) + ["", ""])[:3]
        if keys.startswith("@@"):
            tabs.append((keys[2:], desc, []))
        elif keys.startswith("@"):
            group = keys[1:]
            tabs[-1][2].append(("head", group, desc))
        elif tabs:
            tabs[-1][2].append(("item", keys, desc, cmd, group))
    return tabs


def keycaps(keys, hot, terminal):
    """'[Ctrl+a] [Space]' → keys drawn as keycaps; text outside [ ] stays plain."""
    if terminal:
        return f"{GREEN}{keys}{RESET}"
    back = HOVER if hot else ""
    out = []
    for chip, plain in re.findall(r"\[([^\]]*)\]|([^\[]+)", keys):
        if chip:
            out.append(f"{CHIP_HOT if hot else CHIP} {chip} {RESET}{back}")
        else:
            out.append(f"{SUB}{plain}{RESET}{back}")
    return "".join(out)


class Guide:
    def __init__(self, screen, tabs):
        self.screen = screen
        self.tabs = tabs
        # noted now: another terminal opening a popup later changes @popup-client
        self.client = tmuxlink.client() if os.environ.get("TMUX") else ""
        self.tab = 0
        self.query = ""
        self.top = 0
        self.cur = None
        self.mouse_y = None
        self.hover_tab = None
        self.tab_spans = []    # (x0, x1) of each tab label on the first row
        self.dragging = False
        self.filter()

    # ─── data ───
    def filter(self):
        words = self.query.lower().split()
        if not words:
            self.rows = [r + (self.tabs[self.tab][0],) for r in self.tabs[self.tab][2]]
        else:                                  # search every tab, grouped as "Tab · Group"
            self.rows = []
            for title, _, rows in self.tabs:
                pending = None
                for r in rows:
                    if r[0] == "head":
                        pending = ("head", f"{title} · {r[1]}", "", title)
                        continue
                    hay = f"{r[1]} {r[2]} {r[4]} {title}".lower().replace("[", "").replace("]", "")
                    if all(w in hay for w in words):
                        if pending:
                            self.rows.append(pending)
                            pending = None
                        self.rows.append(r + (title,))
        self.top = 0
        self.cur = self.first_item(0, 1)

    def switch(self, n):
        self.tab = n % len(self.tabs)
        self.query = ""
        self.filter()

    def first_item(self, start, step):
        i = start
        while 0 <= i < len(self.rows):
            if self.rows[i][0] == "item":
                return i
            i += step
        return None

    # ─── geometry ───
    def layout(self):
        self.h, self.w = self.screen.size()
        self.list_h = max(1, self.h - 4)
        self.max_top = max(0, len(self.rows) - self.list_h)
        self.top = min(self.top, self.max_top)

    def scroll(self, delta):
        self.top = max(0, min(self.max_top, self.top + delta))
        if self.mouse_y is not None:
            self.hover(self.mouse_y)

    def ensure_visible(self):
        if self.cur is None:
            return
        if self.cur < self.top:
            self.top = self.cur
        elif self.cur >= self.top + self.list_h:
            self.top = self.cur - self.list_h + 1
        if self.cur > 0 and self.rows[self.cur - 1][0] == "head" and self.cur - 1 < self.top:
            self.top = self.cur - 1   # keep the group title in view

    def row_at(self, y):
        i = self.top + (y - TOP)
        return i if TOP <= y < TOP + self.list_h and 0 <= i < len(self.rows) else None

    def hover(self, y):
        i = self.row_at(y)
        if i is not None and self.rows[i][0] == "item":
            self.cur = i

    def move(self, step):
        start = (self.cur if self.cur is not None else -1) + step
        nxt = self.first_item(start, 1 if step > 0 else -1)
        if nxt is not None:
            self.cur = nxt
            self.ensure_visible()

    # ─── drawing ───
    def draw(self):
        self.layout()
        w, lines = self.w, []
        searching = bool(self.query.strip())

        # row 1: title · tabs · search
        head = f" {ICON_HELP} {BOLD}{ACCENT}guide{RESET}  "
        x = vlen(head) + 1
        self.tab_spans = []
        for n, (title, _, _) in enumerate(self.tabs):
            label = f" {TAB_ICONS.get(title, '•')} {title} " if w >= 90 else f" {title} "
            if n == self.tab and not searching:
                style = ACTIVE_TAB
            elif n == self.hover_tab:
                style = HOVER + TEXT
            else:
                style = SURFACE + SUB
            head += f"{style}{label}{RESET} "
            self.tab_spans.append((x, x + len(label) - 1))
            x += len(label) + 1
        search = f"  {DIM}{ICON_SEARCH} search ❯ {RESET}{TEXT}{self.query}{RESET}{YELLOW}▏"
        lines.append(cut(head + search, w))

        # row 2: what this tab is · help
        sub = f" {DIM}results from every tab" if searching else f" {DIM}{self.tabs[self.tab][1]}"
        hint = "tab switches · type to search · esc closes "
        pad = w - vlen(sub) - len(hint)
        lines.append(cut(sub + (RESET + " " * pad + DIM + hint if pad > 1 else ""), w))
        lines.append(DIM + "─" * w)

        total = len(self.rows)
        bar = total > self.list_h
        if bar:
            th = max(1, self.list_h * self.list_h // total)
            ty = (self.list_h - th) * self.top // max(1, self.max_top)
        text_w = w - (2 if bar else 0)

        for n in range(self.list_h):
            i = self.top + n
            line = ""
            if i < total:
                r = self.rows[i]
                if r[0] == "head":
                    line = f" {ACCENT}{BOLD}▌{r[1]}{RESET}  {DIM}{ellipsis(r[2], text_w - len(r[1]) - 5)}"
                else:
                    line = self.item(r, i == self.cur, text_w)
            line = cut(line, text_w)
            if bar:
                line += RESET + CLEAR_EOL + f"\x1b[{w}G" + (THUMB + "█" if ty <= n < ty + th else TRACK + "│")
            lines.append(line)

        foot = ""
        if self.cur is not None and self.cur < total:
            foot = (f" {GREEN}{ICON_RUN} click or Enter runs it" if self.rows[self.cur][3]
                    else f" {DIM}information only")
        count = f"{sum(1 for r in self.rows if r[0] == 'item')} entries "
        if w - len(count) - 1 > vlen(foot):
            foot += RESET + CLEAR_EOL + f"\x1b[{w - len(count) + 1}G" + DIM + count
        lines.append(cut(foot, w))
        self.screen.paint(lines)

    @staticmethod
    def item(r, hot, width):
        keys, desc, cmd, tab = r[1], r[2], r[3], r[5]
        caps = keycaps(keys, hot, tab == "Terminal")
        kw = max(KEYS_W, vlen(caps) + 2) if width >= 70 else vlen(caps) + 2
        d = ellipsis(desc, max(0, width - 3 - kw))
        mark = f"{GREEN}▶{RESET}{HOVER if hot else ''}" if (hot and cmd) else " "
        body = f" {mark} {caps}{' ' * (kw - vlen(caps))}{TEXT if hot else SUB}{d}"
        return highlight(body, width) if hot else body

    # ─── actions ───
    def run(self, i):
        if i is None or self.rows[i][0] != "item" or not self.rows[i][3]:
            return
        cmd = self.rows[i][3]
        self.screen.restore()
        if not os.environ.get("TMUX"):
            print("Open tmux (terminal) to run actions from the guide.")
            sys.exit(0)
        client = self.client                               # the terminal that opened the guide
        if cmd == "@picker":
            os.execvp("zsh", ["zsh", os.path.join(os.path.dirname(os.path.realpath(__file__)), "terminal.zsh"), "pick"])
        if cmd.startswith("@shell:"):
            os.execvp("zsh", ["zsh", "-c", cmd[len("@shell:"):]])
        if cmd == "@menu":
            cmd = f"send-keys -K -c '{client}' C-a Space"
        elif cmd.startswith("@keys:"):
            cmd = f"send-keys -K -c '{client}' C-a {cmd[len('@keys:'):]}"
        # run after the popup closes so prompts and splits land in the real pane
        subprocess.run(["tmux", "run-shell", "-b", "-d", "0.1", "-C", cmd])
        sys.exit(0)

    # ─── input ───
    def on_key(self, name):
        if name == "esc":
            if not self.query:
                raise SystemExit
            self.query = ""
            self.filter()
        elif name == "enter":
            self.run(self.cur)
        elif name == "backspace":
            self.query = self.query[:-1]
            self.filter()
        elif name == "ctrl-u":
            self.query = ""
            self.filter()
        elif name in ("ctrl-c", "ctrl-d"):
            raise SystemExit
        elif name in ("tab", "right") and not self.query:
            self.switch(self.tab + 1)
        elif name == "left" and not self.query:
            self.switch(self.tab - 1)
        elif name in ("up", "down"):
            self.mouse_y = None
            self.move(-1 if name == "up" else 1)
        elif name in ("pgup", "pgdn"):
            self.mouse_y = None
            self.scroll(-self.list_h if name == "pgup" else self.list_h)
            self.cur = self.first_item(self.top, 1)
        elif name == "home":
            self.top, self.cur = 0, self.first_item(0, 1)
        elif name == "end":
            self.top, self.cur = self.max_top, self.first_item(len(self.rows) - 1, -1)

    def tab_at(self, x, y):
        if y == 1:
            for n, (x0, x1) in enumerate(self.tab_spans):
                if x0 <= x <= x1:
                    return n
        return None

    def on_mouse(self, b, x, y, released):
        on_bar = len(self.rows) > self.list_h and x >= self.w - 1 and TOP <= y < TOP + self.list_h
        if b in (64, 65):                                  # wheel
            self.mouse_y = y
            self.scroll(-WHEEL_STEP if b == 64 else WHEEL_STEP)
        elif b & 32:                                       # motion: hover, or dragging the scrollbar
            self.mouse_y = y
            self.hover_tab = self.tab_at(x, y)
            if self.dragging and b & 3 == 0:
                self.bar_jump(y)
            else:
                self.hover(y)
        elif b == 0 and not released:                      # left press
            t = self.tab_at(x, y)
            if t is not None:
                self.switch(t)
            elif on_bar:
                self.dragging = True
                self.bar_jump(y)
            else:
                self.hover(y)
                self.run(self.row_at(y))
        elif released:
            self.dragging = False

    def bar_jump(self, y):
        frac = (y - TOP) / max(1, self.list_h - 1)
        self.top = max(0, min(self.max_top, round(frac * self.max_top)))
        if self.cur is not None and not (self.top <= self.cur < self.top + self.list_h):
            self.cur = self.first_item(self.top, 1)


def main():
    try:
        run_guide()
    except SystemExit as e:
        sys.exit(0 if e.code is None else e.code)


def run_guide():
    with Screen() as screen:
        guide = Guide(screen, load())
        if len(sys.argv) > 1:                  # `keys git`: open with that search typed in
            guide.query = " ".join(sys.argv[1:])
            guide.filter()
        guide.draw()
        for ev in screen.events():
            if ev[0] == "mouse":
                guide.on_mouse(*ev[1:])
            elif ev[0] == "key":
                guide.on_key(ev[1])
            elif ev[0] == "char":
                guide.query += ev[1]
                guide.filter()
            guide.draw()


if __name__ == "__main__":
    main()
