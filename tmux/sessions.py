#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Session picker · Ctrl+a s, click on the session, `terminal`, new terminal tabs
#  Opened by `tmux/terminal.zsh pick`.
#
#  Mouse: hover highlights and previews · click opens · right-click: menu with
#         open / rename / close (close asks first) / session tree · wheel scrolls
#  Keys:  type to filter · ↑↓ PgUp PgDn Home End move · Enter open · Ctrl+n new
#         · Ctrl+r rename · Ctrl+e describe · Ctrl+x close (asks first) · Ctrl+t session tree
#         · Ctrl+s new terminals start in this session (again: back to the system monitor)
#         · Esc clears / closes · in a question: y / n, or click its buttons
#  Exit status: 0 when a session was opened, 1 when closed without choosing.
# ═══════════════════════════════════════════════════════════════

import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tmuxlink
from tui import (BLUE, BOLD, CLEAR_EOL, CRUST, DANGER_BG, DIM, GREEN, ACCENT, RED, RESET, SUB, SURFACE,
                 TEXT, YELLOW, Menu, Screen, cut, ellipsis, highlight, vlen)

ICON_TERM, ICON_SEARCH, ICON_NEW = "\U000F018D", "\U000F0349", "\U000F0415"
ICON_EDIT, ICON_CLOSE, ICON_FOLDER, ICON_OPEN = "\U000F03EB", "\U000F0156", "\U000F024B", "\U000F0599"
ICON_TREE, ICON_MONITOR, ICON_RESTART = "\U000F0645", "\U000F0430", "\U000F0450"
MONITOR = "system"     # tmux/system.sh: always there, always first
DESCRIPTIONS = os.path.expanduser("~/.tmux/descriptions.tsv")   # session name → what it is for
ICON_DESCRIBE = "\U000F0369"
ICON_START = "\U000F02DC"
START = os.path.expanduser("~/.tmux/start-session")   # "name<TAB>folder": new terminals open it (terminal.zsh)


def read_start():
    """The session new terminals open (tmux/terminal.zsh autostart): the monitor when none is set."""
    try:
        with open(START, encoding="utf-8") as f:
            name = f.readline().rstrip("\n").split("\t", 1)[0]
    except OSError:
        return MONITOR
    return name or MONITOR


def write_start(name, folder=""):
    """New terminals open name (created in folder when it is not running) · MONITOR clears it."""
    if not name or name == MONITOR:
        try:
            os.remove(START)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(START), exist_ok=True)
    tmp = START + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"{name}\t{folder or os.path.expanduser('~')}\n")
    os.replace(tmp, START)



def read_descriptions():
    out = {}
    try:
        with open(DESCRIPTIONS, encoding="utf-8") as f:
            for line in f:
                name, _, text = line.rstrip("\n").partition("\t")
                if name and text:
                    out[name] = text
    except FileNotFoundError:
        pass
    return out


def write_descriptions(d):
    with open(DESCRIPTIONS, "w", encoding="utf-8") as f:
        for name in sorted(d):
            f.write(f"{name}\t{d[name]}\n")
TOP = 3            # first list row on screen (1-based)
WHEEL_STEP = 3
HOME = os.path.expanduser("~")


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def session_of(client):
    """The session a client shows (display -c only says where a message goes, not whose #S)."""
    for line in tmux("list-clients", "-F", "#{client_name}\t#{client_session}").stdout.splitlines():
        name, _, sess = line.partition("\t")
        if name == client:
            return sess
    return ""


def tilde(path):
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + "/") else path


def clean_name(name):
    """tmux does not allow '.' or ':' in session names (a leading '-' would read as an option)."""
    return re.sub(r"\s+", "-", re.sub(r"[.:]", "-", name.strip())).lstrip("-")


class Picker:
    def __init__(self, screen):
        self.screen = screen
        self.inside = bool(os.environ.get("TMUX"))
        self.client = tmuxlink.client() if self.inside else ""        # the terminal that opened the popup
        self.here = session_of(self.client) if self.inside else ""
        self.cwd = os.getcwd()
        self.query = ""
        self.top = 0
        self.cur = 0
        self.mode = "list"     # list · kill · rename · new-name · new-dir
        self.target = ""       # session the kill / rename prompt is about
        self.text = ""         # what is being typed in a prompt
        self.new_name = ""
        self.msg = ""          # one-line feedback (errors in red)
        self.menu = None       # open right-click menu
        self.buttons = {}      # name → (row, x0, x1) of the clickable confirm buttons
        self.start = read_start()
        self.refresh()
        self.cur = 1 if len(self.rows) > 1 else 0   # start on the first session, not on "new"

    # ─── data ───
    def refresh(self):
        out = tmux("ls", "-F", "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_path}"
                   "\t#{@description}").stdout
        self.sessions = [l.split("\t") for l in out.splitlines() if l.count("\t") == 4]
        # descriptions survive tmux restarts in the file: put them back on the sessions
        saved = read_descriptions()
        for s in self.sessions:
            if not s[4] and s[0] in saved:
                s[4] = saved[s[0]]
                tmux("set", "-t", f"{s[0]}:", "@description", s[4])
        self.filter(keep_cursor=True)

    def filter(self, keep_cursor=False):
        words = self.query.lower().split()
        match = [s for s in self.sessions if all(w in f"{s[0]} {tilde(s[3])}".lower() for w in words)]
        match.sort(key=lambda s: s[0] != MONITOR)      # the system monitor first
        self.rows = [("new",)] + [("session", *s) for s in match]
        if not keep_cursor:
            self.top = 0
            self.cur = 1 if len(self.rows) > 1 else 0
        self.cur = min(self.cur, len(self.rows) - 1)

    def current(self):
        return self.rows[self.cur] if 0 <= self.cur < len(self.rows) else ("new",)

    # ─── geometry ───
    def layout(self):
        self.h, self.w = self.screen.size()
        self.list_h = max(1, self.h - 3)
        self.max_top = max(0, len(self.rows) - self.list_h)
        self.top = min(self.top, self.max_top)
        self.list_w = self.w if self.w < 70 else max(34, self.w * 2 // 5)

    def row_at(self, y):
        i = self.top + (y - TOP)
        return i if TOP <= y < TOP + self.list_h and 0 <= i < len(self.rows) else None

    def ensure_visible(self):
        if self.cur < self.top:
            self.top = self.cur
        elif self.cur >= self.top + self.list_h:
            self.top = self.cur - self.list_h + 1

    # ─── drawing ───
    def draw(self):
        self.layout()
        self.buttons = {}
        w, lw = self.w, self.list_w
        head = (f" {ICON_TERM}  {BOLD}{BLUE}sessions{RESET}   {DIM}{ICON_SEARCH} filter ❯ {RESET}"
                f"{TEXT}{self.query}{RESET}{YELLOW}▏" if self.mode == "list"
                else f" {ICON_TERM}  {BOLD}{BLUE}sessions{RESET}")
        hint = "click opens · right-click menu · esc closes "
        pad = w - vlen(head) - len(hint)
        lines = [cut(head + (RESET + " " * pad + DIM + hint if pad > 1 else ""), w), DIM + "─" * w]

        preview = self.preview(w - lw - 3) if w >= 70 else []
        for n in range(self.list_h):
            i = self.top + n
            row = self.row(i, lw) if i < len(self.rows) else ""
            if preview:
                row = (cut(row, lw) + RESET + CLEAR_EOL + f"\x1b[{lw + 2}G" + DIM + "│" + RESET + " "
                       + (preview[n] if n < len(preview) else ""))
            lines.append(cut(row, w))
        lines.append(cut(self.footer(TOP + self.list_h), w))
        self.screen.paint(lines)
        if self.menu:
            self.menu.draw()

    def row(self, i, width):
        r, hot = self.rows[i], i == self.cur
        if r[0] == "new":
            name = clean_name(self.query)
            label = f"new session {BOLD}{name}{RESET}{GREEN}" if name else "new session"
            body = f" {GREEN}{ICON_NEW}  {label}{RESET}  {DIM}{'click or Enter' if hot else ''}"
            return highlight(body, width) if hot else body

        _, name, wins, attached, path, desc = r
        if self.mode == "kill" and name == self.target:
            what = "will be rebuilt" if name == MONITOR else "will be closed"
            return DANGER_BG + CRUST + cut(f" {ICON_CLOSE} {name}  {what}", width).ljust(width) + RESET
        if name == self.here:
            mark = f"{ACCENT}▶"
        elif name == MONITOR:
            mark = f"{ACCENT}{ICON_MONITOR}"
        elif attached != "0":
            mark = f"{GREEN}●"
        else:
            mark = f"{DIM}○"
        info = f"{wins} win · {tilde(path)}"
        if desc:
            info = f"{TEXT}{desc}{RESET}{DIM} · {info}"
        start = f" {YELLOW}{ICON_START}{RESET}" if name == self.start else ""
        extra = 2 if start else 0
        name_w = min(len(name), max(4, width - 6 - extra))
        body = (f" {mark}{RESET} {TEXT}{BOLD}{ellipsis(name, name_w)}{RESET}{start}  "
                f"{DIM}{ellipsis(info, max(0, width - name_w - 6 - extra))}")
        return highlight(body, width) if hot else body

    def preview(self, width):
        """Right column: windows of the highlighted session and what its active pane shows."""
        r = self.current()
        rows = self.list_h
        if r[0] == "new":
            name = clean_name(self.query) or "…"
            return [cut(l, width) for l in (
                f"{GREEN}{BOLD}New session{RESET}", "",
                f"{TEXT}Type a name and press Enter, or click the row.",
                f"{DIM}Then choose its folder (Enter keeps {tilde(self.cwd)}).", "",
                f"{DIM}Name so far: {RESET}{TEXT}{name}")][:rows]
        name = r[1]
        out = [f"{BLUE}{BOLD}{name}{RESET}  {DIM}{tilde(r[4])}"]
        if r[5]:
            out.append(f"{TEXT}{r[5]}")
        if name == self.start and name != MONITOR:
            out.append(f"{YELLOW}{ICON_START}  new terminals open this session{DIM} · ctrl-s: back to the monitor")
        elif name == self.start:
            out.append(f"{YELLOW}{ICON_START}  new terminals open the monitor{DIM} · ctrl-s on a session changes it")
        elif name == MONITOR and not any(s[0] == self.start for s in self.sessions):
            out.append(f"{YELLOW}{ICON_START}  new terminals open «{self.start}»{DIM} · not running now: "
                       f"the next terminal creates it · ctrl-s here: the monitor again")
        for l in tmux("list-windows", "-t", f"={name}",
                      "-F", "#{?window_active,▶,·}\t#I\t#W\t#{window_panes}").stdout.splitlines():
            act, idx, wname, panes = l.split("\t")
            out.append(f"{ACCENT if act == '▶' else DIM}{act}{RESET} {SUB}{idx} {TEXT}{wname}{RESET} "
                       f"{DIM}({panes} pane{'s' if panes != '1' else ''})")
        out.append(DIM + "─" * max(0, width - 1))
        cap = tmux("capture-pane", "-ep", "-t", f"={name}:").stdout.rstrip("\n").split("\n")
        while cap and not cap[-1].strip():
            cap.pop()
        out += cap[-max(0, rows - len(out)):] if rows > len(out) else []
        return [cut(l, width) for l in out[:rows]]

    def footer(self, y):
        if self.mode == "kill":
            n = next((s[1] for s in self.sessions if s[0] == self.target), "?")
            if self.target == MONITOR:          # it is always there: closing it means rebuilding it
                text = f" {RED}{BOLD}Restart the system monitor?{RESET} {SUB}its panes start again  "
                yes = f"{DANGER_BG}{CRUST}{BOLD} y  restart {RESET}"
            else:
                text = f" {RED}{BOLD}Close session «{self.target}»?{RESET} {SUB}its {n} window(s) and their programs end  "
                yes = f"{DANGER_BG}{CRUST}{BOLD} y  close {RESET}"
            no = f"{SURFACE}{TEXT} n  cancel {RESET}"
            x = vlen(text) + 1
            self.buttons["yes"] = (y, x, x + vlen(yes) - 1)
            self.buttons["no"] = (y, x + vlen(yes) + 2, x + vlen(yes) + 2 + vlen(no) - 1)
            return text + yes + "  " + no
        if self.mode == "describe":
            return (f" {BLUE}{ICON_DESCRIBE}  What is «{self.target}» for? {RESET}{TEXT}{self.text}{YELLOW}▏{RESET}"
                    f"  {DIM}enter save (empty removes) · esc cancel")
        if self.mode == "rename":
            return f" {BLUE}{ICON_EDIT}  Rename «{self.target}» to: {RESET}{TEXT}{self.text}{YELLOW}▏{RESET}  {DIM}enter save · esc cancel"
        if self.mode == "new-name":
            return f" {GREEN}{ICON_NEW}  New session name: {RESET}{TEXT}{self.text}{YELLOW}▏{RESET}  {DIM}enter next · esc cancel"
        if self.mode == "new-dir":
            return (f" {GREEN}{ICON_FOLDER}  Folder for «{self.new_name}»: {RESET}{TEXT}{self.text}{YELLOW}▏{RESET}"
                    f"  {DIM}enter create · esc back")
        if self.msg:
            return " " + self.msg
        # the longest hint that fits (a cut one would end mid-word)
        for hint in ("enter open · right-click for more · ctrl-n new · ctrl-r rename · ctrl-e describe · ctrl-x close · ctrl-s start here · ctrl-t tree",
                     "enter open · right-click for more · ctrl-n new · ctrl-r rename · ctrl-e describe · ctrl-x close · ctrl-t tree",
                     "enter open · right-click for more · ctrl-n new · ctrl-r rename · ctrl-x close · ctrl-t tree",
                     "enter open · right-click for more · ctrl-n new · ctrl-x close",
                     "enter open · right-click for more",
                     "right-click for more"):
            if len(hint) + 2 <= self.w:
                break
        return f" {DIM}{hint}"

    # ─── actions ───
    def open(self, name):
        if self.inside:
            tmux("switch-client", "-c", self.client, "-t", f"={name}")
            sys.exit(0)
        self.screen.restore()
        os.execvp("tmux", ["tmux", "attach-session", "-t", f"={name}"])

    def tree(self):
        """Hand over to tmux's session tree (Ctrl+a S).

        Inside tmux (popup): replay Ctrl+a S once the popup is gone. Outside (the
        full-screen picker of a new terminal tab): attach to the highlighted session,
        or the first one, and open the tree right away.
        """
        if self.inside:
            tmux("run-shell", "-b", "-d", "0.1", "-C", f"send-keys -K -c '{self.client}' C-a S")
            sys.exit(0)
        r = self.current()
        name = r[1] if r[0] == "session" else (self.sessions[0][0] if self.sessions else "")
        if not name:
            self.msg = f"{RED}no sessions yet: create one first"
            return
        self.screen.restore()
        os.execvp("tmux", ["tmux", "attach-session", "-t", f"={name}", ";",
                           "choose-tree", "-Zw", "-F", "#{E:@tree-format}"])

    def start_new(self):
        self.mode, self.text, self.msg = "new-name", clean_name(self.query), ""

    def create(self):
        folder = os.path.expanduser(self.text.strip() or tilde(self.cwd))
        if not os.path.isdir(folder):
            self.msg, self.mode = f"{RED}folder not found: {folder}", "list"
            return
        res = tmux("new-session", "-d", "-s", self.new_name, "-c", folder)
        if res.returncode:
            self.msg, self.mode = f"{RED}{res.stderr.strip()}", "list"
            return
        self.open(self.new_name)

    def kill(self):
        name, self.mode = self.target, "list"
        if name == MONITOR:
            self.restart_monitor()
            return
        tmux("kill-session", "-t", f"={name}")
        d = read_descriptions()
        if d.pop(name, None) is not None:
            write_descriptions(d)
        if self.inside and name == self.here:
            # this popup's own session: tmux has moved the client to another one and the
            # popup stays open, so just carry on picking from what is left
            self.here = session_of(self.client)
        self.msg = f"{GREEN}closed «{name}»"
        self.refresh()
        if not self.sessions:            # nothing left: tmux has detached us
            sys.exit(0)

    def rename(self):
        new, old, self.mode = clean_name(self.text), self.target, "list"
        if not new or new == old:
            return
        if new == MONITOR:                       # tmux/system.sh would take it for the monitor
            self.msg = f"{YELLOW}«{MONITOR}» is the system monitor's name"
            return
        res = tmux("rename-session", "-t", f"={old}", new)
        d = read_descriptions()
        if not res.returncode and old in d:
            d[new] = d.pop(old)
            write_descriptions(d)
        if res.returncode:
            self.msg = f"{RED}{res.stderr.strip()}"
        else:
            if old == self.here:
                self.here = new
            if old == self.start:                    # new terminals follow the rename
                folder = next((s[3] for s in self.sessions if s[0] == old), "")
                write_start(new, folder)
                self.start = new
            self.msg = f"{GREEN}renamed «{old}» → «{new}»"
        self.refresh()

    def activate(self, i):
        if i is None:
            return
        r = self.rows[i]
        if r[0] == "new":
            name = clean_name(self.query)
            if name:
                self.new_name = name
                self.mode, self.text = "new-dir", tilde(self.cwd)
            else:
                self.start_new()
        elif r[0] == "session":
            self.open(r[1])

    def toggle_start(self, i):
        """New terminals open this session · again (or on the monitor): back to the monitor."""
        if i is None or self.rows[i][0] != "session":
            return
        name, path = self.rows[i][1], self.rows[i][4]
        if name == MONITOR or name == self.start:
            write_start(MONITOR)
            self.start = MONITOR
            self.msg = f"{GREEN}new terminals open the system monitor"
        else:
            write_start(name, path)
            self.start = name
            self.msg = f"{GREEN}new terminals open «{name}» (created in {tilde(path)} when it is not running)"

    def restart_monitor(self):
        subprocess.run([os.path.join(os.path.dirname(os.path.realpath(__file__)), "system.sh"), "restart"], capture_output=True)
        self.msg = f"{GREEN}system monitor rebuilt"
        self.refresh()

    def ask_kill(self, i):
        if i is not None and self.rows[i][0] == "session":
            self.cur, self.mode, self.target, self.msg = i, "kill", self.rows[i][1], ""

    def ask_describe(self, i):
        if i is not None and self.rows[i][0] == "session":
            if self.rows[i][1] == MONITOR:
                self.msg = f"{YELLOW}the system monitor describes itself"
                return
            self.cur, self.mode, self.target, self.text, self.msg = i, "describe", self.rows[i][1], self.rows[i][5], ""

    def describe(self):
        name, text, self.mode = self.target, self.text.strip().replace("\t", " "), "list"
        d = read_descriptions()
        if text:
            d[name] = text
            tmux("set", "-t", f"{name}:", "@description", text)
        else:
            d.pop(name, None)
            tmux("set", "-u", "-t", f"{name}:", "@description")
        write_descriptions(d)
        self.msg = f"{GREEN}{'described' if text else 'description removed'}: «{name}»"
        self.refresh()

    def ask_rename(self, i):
        if i is not None and self.rows[i][0] == "session" and self.rows[i][1] == MONITOR:
            self.msg = f"{YELLOW}the system monitor keeps its name (it is rebuilt by it)"
            return
        if i is not None and self.rows[i][0] == "session":
            self.cur, self.mode, self.target, self.text, self.msg = i, "rename", self.rows[i][1], self.rows[i][1], ""

    def open_menu(self, i, x, y):
        """Right-click menu for a row (or for the empty part of the list)."""
        if i is not None and self.rows[i][0] == "session":
            self.cur = i
            name = self.rows[i][1]
            if name == MONITOR:
                self.menu = Menu(name, [
                    (f"{ICON_OPEN}  Open" + ("  (you are here)" if name == self.here else ""), "o",
                     lambda: self.open(name)),
                    (f"{ICON_RESTART}  Restart the monitor…", "r", lambda: self.ask_kill(i)),
                    (f"{ICON_START}  New terminals start here" + ("  (they do)" if self.start == MONITOR else ""), "s",
                     None if self.start == MONITOR else (lambda: self.toggle_start(i))),
                    ("", "", None),
                    (f"{ICON_NEW}  New session…", "n", self.start_new),
                    (f"{ICON_TREE}  Session tree", "t", self.tree)], x, y, self.h, self.w)
                return
            items = [(f"{ICON_OPEN}  Open" + ("  (you are here)" if name == self.here else ""), "o",
                      lambda: self.open(name)),
                     (f"{ICON_EDIT}  Rename…", "r", lambda: self.ask_rename(i)),
                     (f"{ICON_DESCRIBE}  Describe…", "d", lambda: self.ask_describe(i)),
                     (f"{ICON_START}  New terminals start here", "s", lambda: self.toggle_start(i)) if name != self.start
                     else (f"{ICON_START}  New terminals start in the monitor again", "s", lambda: self.toggle_start(i)),
                     ("", "", None),
                     (f"{ICON_NEW}  New session…", "n", self.start_new),
                     (f"{ICON_TREE}  Session tree", "t", self.tree),
                     ("", "", None),
                     (f"{ICON_CLOSE}  Close session…", "x", lambda: self.ask_kill(i))]
            title = ellipsis(name, 30)
        else:
            items = [(f"{ICON_NEW}  New session…", "n", self.start_new),
                     (f"{ICON_TREE}  Session tree", "t", self.tree)]
            title = "sessions"
        self.menu = Menu(title, items, x, y, self.h, self.w)

    # ─── input ───
    def on_char(self, ch):
        if self.mode == "kill":
            if ch.lower() == "y":
                self.kill()
            elif ch.lower() == "n":
                self.mode = "list"
        elif self.mode in ("rename", "describe", "new-name", "new-dir"):
            self.text += ch
        else:
            self.query += ch
            self.msg = ""
            self.filter()

    def on_key(self, name):
        mode = self.mode
        if mode == "kill":                       # only y / n / esc / clicks decide
            if name in ("esc", "ctrl-c"):
                self.mode = "list"
            return
        if mode in ("rename", "describe", "new-name", "new-dir"):
            if name == "esc":
                self.mode = "new-name" if mode == "new-dir" else "list"
                if mode == "new-dir":
                    self.text = self.new_name
            elif name == "backspace":
                self.text = self.text[:-1]
            elif name == "ctrl-u":
                self.text = ""
            elif name == "enter":
                if mode == "rename":
                    self.rename()
                elif mode == "describe":
                    self.describe()
                elif mode == "new-name":
                    new = clean_name(self.text)
                    if new == MONITOR and not any(s[0] == new for s in self.sessions):
                        self.msg, self.mode = f"{YELLOW}«{MONITOR}» is the system monitor's name", "list"
                    elif new and any(s[0] == new for s in self.sessions):
                        self.open(new)
                    elif new:
                        self.new_name, self.mode, self.text = new, "new-dir", tilde(self.cwd)
                else:
                    self.create()
            return

        if name not in ("up", "down"):
            self.msg = ""
        if name == "esc":
            if not self.query:
                sys.exit(1)
            self.query = ""
            self.filter()
        elif name in ("ctrl-c", "ctrl-d"):
            sys.exit(1)
        elif name == "enter":
            self.activate(self.cur)
        elif name == "backspace":
            self.query = self.query[:-1]
            self.filter()
        elif name == "ctrl-u":
            self.query = ""
            self.filter()
        elif name == "ctrl-n":
            self.start_new()
        elif name == "ctrl-r":
            self.ask_rename(self.cur)
        elif name == "ctrl-e":
            self.ask_describe(self.cur)
        elif name == "ctrl-x":
            self.ask_kill(self.cur)
        elif name == "ctrl-t":
            self.tree()
        elif name == "ctrl-s":
            self.toggle_start(self.cur)
        elif name in ("up", "down"):
            self.cur = max(0, min(len(self.rows) - 1, self.cur + (-1 if name == "up" else 1)))
            self.ensure_visible()
        elif name in ("pgup", "pgdn", "home", "end"):
            step = {"pgup": -self.list_h, "pgdn": self.list_h, "home": -len(self.rows), "end": len(self.rows)}[name]
            self.cur = max(0, min(len(self.rows) - 1, self.cur + step))
            self.ensure_visible()

    def hit(self, x, y):
        for name, (row, x0, x1) in self.buttons.items():
            if y == row and x0 <= x <= x1:
                return name
        return None

    def on_mouse(self, b, x, y, released):
        if b in (64, 65):
            self.top = max(0, min(self.max_top, self.top + (-WHEEL_STEP if b == 64 else WHEEL_STEP)))
            b, released = 35, False                      # re-hover under the pointer after scrolling
        if b & 32:                                       # motion → hover (not while a prompt is open)
            if self.mode == "list" and x <= self.list_w:
                i = self.row_at(y)
                if i is not None:
                    self.cur = i
            return
        if released or b not in (0, 2):
            return
        button = self.hit(x, y)
        if self.mode == "kill":
            if b == 0 and button == "yes":
                self.kill()
            else:                                        # any other click cancels
                self.mode = "list"
            return
        if self.mode != "list":                          # clicking away cancels a prompt
            self.mode = "list"
            return
        if b == 2:
            self.open_menu(self.row_at(y) if x <= self.list_w else None, x, y)
        elif x <= self.list_w:
            self.activate(self.row_at(y))

    def dispatch(self, ev):
        if self.menu:                                    # an open menu gets everything first
            if ev[0] == "mouse":
                res = self.menu.on_mouse(*ev[1:])
            elif ev[0] in ("key", "char"):
                res = self.menu.on_key(ev[0], ev[1])
            else:
                res = ("close",)                         # resize: drop the menu
            if res:
                self.menu = None
                if res[0] == "pick":
                    res[1]()
            return
        if ev[0] == "mouse":
            self.on_mouse(*ev[1:])
        elif ev[0] == "key":
            self.on_key(ev[1])
        elif ev[0] == "char":
            self.on_char(ev[1])


def main():
    with Screen() as screen:
        picker = Picker(screen)
        picker.draw()
        try:
            for ev in screen.events():
                picker.dispatch(ev)
                picker.draw()
        except SystemExit:
            screen.restore()
            raise


if __name__ == "__main__":
    main()
