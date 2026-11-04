#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Folders pane of the `disk` tab (tmux/system.sh) · what takes the space, like ncdu:
#  the files and folders of one folder by size, with their share of it.
#  Starts in your home. du measures the whole folder once, in the background
#  (sizes fill in as it goes), so moving into a subfolder is instant; it stays
#  on one disk (another disk mounted inside shows as such: open it to measure it).
#
#  Double-click a folder: go into it (.. or Backspace: up) · a file: open it with
#  the system's app. Right-click: open · up · open with the system's app (Explorer
#  in WSL) · a terminal session here · measure again · copy the path · delete (asks,
#  says how much; not for the home folder, / or the folders right under it).
#  The Disks pane sends you to a disk; Cleanup to the folder of a cache.
# ═══════════════════════════════════════════════════════════════

import os
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import disksrc
import tmuxlink
from disksrc import Measure, ago, bar, human, tilde
from table import Column, TableApp, run
from tui import BLUE, DIM, RED, SUB, TEXT, YELLOW

HERE = os.path.dirname(os.path.realpath(__file__))
ICON = dict(dir="\U000F024B", file="\U000F0214", link="\U000F0339", up="\U000F005D", open="\U000F0770",
            app="\U000F03D6", term="\U000F018D", measure="\U000F0450", copy="\U000F018F", delete="\U000F0A7A",
            home="\U000F02DC", disk="\U000F02CA")
STALE = 1800           # a measure older than this (seconds) is done again when you go to the folder
RUNS = (".exe", ".bat", ".cmd", ".com", ".lnk", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
        ".hta", ".cpl", ".msc", ".reg", ".pif", ".scf", ".msi", ".url", ".scr", ".desktop", ".command", ".app",
        ".sh", ".appimage", ".jar", ".pkg")


def same(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def protected(path):
    """Folders the Delete item never offers, whatever the way you reached them (by inode, not
    only by name): /, your home and its parent, the folders right under / or under any mounted
    disk, mount points, Windows' own folders and users in WSL, ~/Library and the system's
    folders on macOS."""
    path = path.rstrip("/") or "/"
    home = disksrc.HOME
    if path.count("/") <= 1 or same(path, home) or same(path, os.path.dirname(home)) or os.path.ismount(path) \
            or path in disksrc.mount_points():
        return True
    parent = os.path.dirname(path)
    if os.path.ismount(parent) or parent in disksrc.mount_points():
        return True                                  # right under a disk: C:\Windows, /Volumes/USB/…
    if disksrc.WSL and len(path.split("/")) <= 5 and path.split("/")[1:2] == ["mnt"]:
        parts = path.split("/")                      # /mnt/c/Users/me · /mnt/c/Program Files…
        if len(parts) >= 4 and parts[3] in ("Users", "Windows", "Program Files", "Program Files (x86)", "ProgramData"):
            return True
    if disksrc.MACOS:
        data = "/System/Volumes/Data"                # the Data volume holds the same tree: /Users/me…
        bare = path[len(data):] if path.startswith(data + "/") else path   # …is also …/Data/Users/me
        if path == data or bare in (os.path.join(home, "Library"), "/Users", "/Applications", "/Library", "/private",
                                    "/opt/homebrew") or os.path.dirname(bare) == "/Users":
            return True
    return False


def shown(name):
    """A file name as text that cannot move the cursor or set colours (control characters → ?)."""
    return "".join("?" if ord(c) < 32 or ord(c) == 127 else c for c in name)


UNSET = object()


RELIST = 5            # seconds a folder's listing (sizes, times) is kept while its mtime stays


class Folders(TableApp):
    icon = "\U000F02CA"
    title = "Folders"
    noun = "items"
    interval = 1.0
    reload_every = 2
    sort_key = "size"
    search_keys = ("name",)
    columns = [Column("name_txt", "NAME", sort="name", min=12),
               Column("size", "SIZE", 7, "r", desc=True, fmt=human),
               Column("share", "SHARE", 16, sort="frac", desc=True, min=15),     # bar + "100%"
               Column("mtime_txt", "MODIFIED", 8, "r", sort="mtime", desc=True, optional=True)]
    watch = ("@disk-go", "@disk-changed")

    def __init__(self, screen):
        self.path = disksrc.HOME
        self.measures = []          # newest first: the folders measured so far (each with its sizes)
        self.listing = {}           # folder → (its mtime, when read, entries)
        self.changed_seen = UNSET   # the first look only notes the value
        self.my_stamp = None        # the @disk-changed this pane wrote (its own deletes need no re-measure)
        self.deleted = []           # (row, ok, output) of deletes that finished: handled on the UI thread
        self.total, self.error = 0, ""
        super().__init__(screen)

    # ─── measuring ───
    def measure_for(self, path):
        """The newest measure that covers path (done or running)."""
        for m in self.measures:
            if m.covers(path) and not m.cancelled:
                return m
        return None

    def ensure_measured(self, path, again=False):
        """The measure that answers for path, starting one when there is none, it is older
        than STALE, or du did not reach path (another disk mounted here, a folder made later)."""
        if not os.path.isdir(path):
            return self.measure_for(path)
        m = self.measure_for(path)
        if m and not again:
            if not m.done:
                return m                              # still running: its sizes fill in
            if path in m.sizes and time.time() - (m.finished or 0) < STALE:
                return m
            if path not in m.sizes and m.partial(path):
                return m                              # no permission: measuring again would not help
        for old in self.measures:
            if not old.done and (not old.covers(path) or old.root == path):
                old.cancel()                          # measuring somewhere you left (or this again)
        m = Measure(path, self.wake)
        self.measures.insert(0, m)
        return m

    def prune(self):
        """Older measures stay as a fallback while a newer one runs, then go (and stop)."""
        keep = []
        for m in self.measures:
            newer_done = any(n.done and not n.cancelled and n.covers(m.root) for n in keep)
            if newer_done or (m.cancelled and keep):
                m.cancel()
                continue
            keep.append(m)
        for m in keep[8:]:
            m.cancel()
        self.measures = keep[:8]

    def size_of(self, path):
        """(bytes or None, measure) of a folder from the newest measure that has it."""
        for m in self.measures:
            size = m.sizes.get(path)
            if size is not None:
                return size, m
        return None, self.measure_for(path)

    # ─── reading ───
    def entries(self, path):
        try:
            mt = os.stat(path).st_mtime
        except OSError:
            return None
        cached = self.listing.get(path)
        # a file that grows (a download, a log) leaves its folder's mtime as it is: read again
        # every few seconds anyway (not every reload: slow on /mnt/c)
        if cached and cached[0] == mt and time.monotonic() - cached[1] < RELIST:
            return cached[2]
        out = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    out.append((e.name, e.path, st))
        except OSError:
            return None
        if len(self.listing) > 50:
            self.listing.clear()
        self.listing[path] = (mt, time.monotonic(), out)
        return out

    def fetch(self):
        self.handle_deleted()
        if not os.path.isdir(self.path):              # deleted from elsewhere: the nearest folder left
            p = self.path
            while p != "/" and not os.path.isdir(p):
                p = os.path.dirname(p)
            self.flash(f"{disksrc.short(self.path)} is gone: showing {disksrc.short(p)}", ok=False)
            self.path = p
        path = self.path
        self.prune()
        m = self.ensure_measured(path)
        found = self.entries(path)
        self.error = f"cannot read {tilde(path)}" if found is None else ""
        rows, total = [], 0
        done = bool(m and m.done)
        mounts = set(disksrc.mount_points())         # (kept 10 s: no ismount() per folder, slow on /mnt/c)
        for name, full, st in found or []:
            is_link = stat.S_ISLNK(st.st_mode)
            is_dir = stat.S_ISDIR(st.st_mode) or (is_link and os.path.isdir(full))   # a link to a folder opens it
            small = False
            if is_dir:
                size, _ = self.size_of(full)
                other_disk = size is None and done and full in mounts
                small = size is None and done and not other_disk and m.small(full)
            else:
                size = st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size     # on disk, like du
                other_disk = False
            total += size or 0
            icon = ICON["link"] if is_link else ICON["dir"] if is_dir else ICON["file"]
            rows.append({"id": full, "name": shown(name), "name_txt": f"{icon} {shown(name)}{'/' if is_dir else ''}",
                         "path": full, "dir": is_dir, "link": is_link, "size": size, "mtime": st.st_mtime,
                         "mtime_txt": ago(st.st_mtime), "other_disk": other_disk, "small": small,
                         "partial": bool(is_dir and m and m.partial(full))})
        own, _ = self.size_of(path)
        self.total = own if own and done else total     # while measuring: what is known so far
        for r in rows:
            frac = (r["size"] or 0) / self.total if self.total else 0
            r["frac"] = frac if r["size"] is not None else None
            r["share"] = (f"{bar(frac, 10)} {frac * 100:3.0f}%" if r["size"] is not None else
                          ("other disk" if r["other_disk"] else "< 1M" if r["small"] else "…" if not done else "?"))
        if path != "/":
            rows.append({"id": "..", "name": "..", "name_txt": f"{ICON['up']} ..", "path": os.path.dirname(path),
                         "dir": True, "link": False, "size": None, "frac": None, "mtime": None, "mtime_txt": "",
                         "share": "", "other_disk": False, "small": False, "partial": False})
        return rows

    def order(self, rows):
        return [r for r in rows if r["id"] == ".."] + [r for r in rows if r["id"] != ".."]

    def apply(self):
        super().apply()
        # a folder you just opened starts on its biggest item, not on ..
        if self.cur_id == ".." and not self.touched and len(self.rows) > 1:
            self.cur_id = self.sel_id = self.rows[1]["id"]

    # ─── look ───
    def summary(self):
        m = self.measure_for(self.path)
        where = f"{TEXT}{disksrc.short(self.path)}"
        if m and not m.done:
            size = f"{DIM} · ≥ {human(self.total)}" if self.total else ""
            return f"{where}{size}{DIM} · {YELLOW}measuring… {m.count:,} folders"
        size = f"{DIM} · {human(self.total)}" if self.total else ""
        if m and m.finished:
            part = f" · {YELLOW}some folders unreadable{DIM}" if m.partial(self.path) else ""
            return f"{where}{size}{DIM}{part} · measured {ago(m.finished)} ago"
        return where + size

    def row_colour(self, r):
        if r["id"] == "..":
            return BLUE
        if r["other_disk"]:
            return DIM
        return TEXT if r["dir"] else SUB

    def detail(self, r):
        if r["id"] == "..":
            return f"{DIM}up to {tilde(r['path'])} · or Backspace"
        bits = [f"{TEXT}{shown(tilde(r['path']))}"]
        if r["link"]:
            try:
                bits.append(f"{DIM}→ {shown(os.readlink(r['path']))}")
            except OSError:
                pass
        if r["size"] is not None:
            frac = r["size"] / self.total if self.total else 0
            bits.append(f"{DIM}{human(r['size'])} · {frac * 100:.1f}% of {tilde(self.path)}")
        if r["other_disk"]:
            bits.append(f"{DIM}another disk mounted here: open it to measure it")
        if r["partial"]:
            bits.append(f"{YELLOW}some folders inside could not be read (no permission): it is at least this big")
        if r["mtime"]:
            bits.append(f"{DIM}modified {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['mtime']))}")
        return f"{DIM} · ".join(bits)

    def footer(self, y):
        if self.error and not (self.ask or self.prompt or self.msg):
            return f" {RED}{self.error}"
        return super().footer(y)

    def menu_title(self, r):
        return r["name"]

    # ─── moving around ───
    def go(self, path):
        path = os.path.realpath(os.path.abspath(path))   # a link to a folder: the folder itself
        if not os.path.isdir(path):
            self.flash(f"{disksrc.short(path)} is not a folder", ok=False)
            return
        for m in self.measures:                         # leaving a folder still being measured: stop it
            if not m.done and not m.covers(path) and not (m.root.startswith(path.rstrip("/") + "/")):
                m.cancel()
        came_from = self.path
        self.path = path
        self.query = ""
        self.jump, self.touched, self.top = True, False, 0
        self.reload()
        if os.path.dirname(came_from) == path:          # going up: stay on the folder you came from
            self.cur_id = self.sel_id = came_from
            self.touched = True
            self.ensure_visible()

    def up(self):
        if self.path != "/":
            self.go(os.path.dirname(self.path))

    def on_tick(self):
        target = self.opts.get("@disk-go")
        if target:
            tmuxlink.put("@disk-go", None)
            self.go(target)
        stamp = self.opts.get("@disk-changed")
        if stamp != self.changed_seen:
            first = self.changed_seen is UNSET
            self.changed_seen = stamp
            _, where = disksrc.read_changed(stamp)
            where = os.path.realpath(where) if where else ""
            here = os.path.realpath(self.path)
            near = not where or where == here or where.startswith(here.rstrip("/") + "/") \
                or here.startswith(where.rstrip("/") + "/")
            if not first and stamp and stamp != self.my_stamp and near:   # changed elsewhere, here: measure again
                self.listing.clear()
                self.ensure_measured(self.path, again=True)

    def on_key(self, name):
        if name == "backspace" and not self.query:
            self.up()
            return
        super().on_key(name)

    def on_double(self, r, col, x):
        if r["dir"]:
            self.go(r["path"])
        else:
            self.open_app(r)

    # ─── menu ───
    def menu_items(self, r):
        if r["id"] == "..":
            return [(f"{ICON['up']}  Up to {disksrc.short(r['path'])}", "u", self.up)]
        items = []
        if r["dir"]:
            items.append((f"{ICON['open']}  Open", "o", lambda: self.go(r["path"])))
        items += [(f"{ICON['app']}  Open with the system's app" + (" (Explorer)" if disksrc.WSL else ""), "a",
                   lambda: self.open_app(r)),
                  (f"{ICON['term']}  Terminal session here", "s", (lambda: self.session(r["path"])) if r["dir"] else None),
                  (f"{ICON['copy']}  Copy the path", "c", lambda: self.copy(r["path"])),
                  ("", "", None),
                  (f"{ICON['delete']}  Delete…", "d", None if protected(r["path"]) else (lambda: self.ask_delete(r))),
                  ("", "", None)]
        return items + self.place_items()

    def empty_menu_items(self):
        return self.place_items()

    def place_items(self):
        return [(f"{ICON['up']}  Up one folder", "u", self.up if self.path != "/" else None),
                (f"{ICON['measure']}  Measure again", "m", self.measure_again),
                (f"{ICON['term']}  Terminal session in {disksrc.short(self.path, 30)}", "S", lambda: self.session(self.path)),
                (f"{ICON['home']}  Go to your home", "h", (lambda: self.go(disksrc.HOME)) if self.path != disksrc.HOME else None)]

    def on_delete(self, r):
        if r["id"] != ".." and not protected(r["path"]):
            self.ask_delete(r)

    # ─── actions ───
    def measure_again(self):
        self.listing.clear()
        self.ensure_measured(self.path, again=True)
        self.flash(f"measuring {disksrc.short(self.path)} again…")

    def open_app(self, r, sure=False):
        """Open with the desktop's app · a program (.exe, .desktop, .sh, executable…) asks first:
        the system would run it."""
        # by its name, and by the executable bit except on a Windows drive (drvfs marks every file so)
        windows_drive = disksrc.WSL and r["path"].startswith("/mnt/") and len(r["path"].split("/")) > 2 \
            and len(r["path"].split("/")[2]) == 1
        name = r["path"].lower()                     # (a .app is a folder, and `open` runs it)
        runs = name.endswith(".app") if r["dir"] else \
            name.endswith(RUNS) or (os.access(r["path"], os.X_OK) and not windows_drive)
        if runs and not sure:
            self.confirm(f"{r['name']} is a program: run it with the system's app?", lambda: self.open_app(r, True), r)
            return
        if tmuxlink.open_url(r["path"]):
            self.flash(f"opening {disksrc.short(r['path'])}")
        else:
            self.flash(f"could not start {tmuxlink.BROWSER}", ok=False)

    def session(self, path):
        name = tmuxlink.session_for(path)
        try:
            subprocess.Popen([os.path.join(HERE, "terminal.zsh"), "open", name, path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.flash(f"session {name} in {disksrc.short(path)}")
        except OSError as e:
            self.flash(f"could not open a session: {e.strerror}", ok=False)

    def ask_delete(self, r):
        size = f" ({human(r['size'])})" if r["size"] else (" (under 1M)" if r.get("small") else
                                                              " (size not known yet)" if r["dir"] else "")
        what = "the folder" if r["dir"] and not r["link"] else "the link" if r["link"] else "the file"
        self.confirm(f"Delete {what} {disksrc.short(r['path'], 40)}{size}? No trash, no undo",
                     lambda: self.delete(r), r)

    def delete(self, r):
        """rm in the background, never across into another disk mounted inside; what comes of it
        is handled on the UI thread (handle_deleted), where the measures live."""
        if r["dir"] and not r["link"]:
            inside = disksrc.mounts_under(r["path"])
            if inside:
                self.flash(f"not deleted: another disk is mounted inside ({disksrc.short(inside[0])})", ok=False)
                return
            argv = ["rm", "-rf"] + (["--one-file-system"] if not disksrc.MACOS else []) + ["--", r["path"]]
        else:
            argv = ["rm", "-f", "--", r["path"]]
        # the highlight goes to the next row (not back to .. at the top)
        ids = [x["id"] for x in self.rows]
        if r["id"] in ids:
            i = ids.index(r["id"])
            nxt = ids[i + 1] if i + 1 < len(ids) else ids[i - 1] if i else None
            self.after_delete = nxt

        def done(ok, out):
            self.deleted.append((r, ok, out))
        self.background(r, "deleting", argv, done, timeout=None)

    def handle_deleted(self):
        while self.deleted:
            r, ok, out = self.deleted.pop(0)
            self.listing.clear()
            if ok:
                self.forget(r)
                self.flash(f"deleted {disksrc.short(r['path'], 40)}" + (f" · {human(r['size'])} freed" if r["size"] else ""))
            else:
                self.flash(f"could not delete it all: {(out.strip().splitlines() or ['?'])[-1][:100]}", ok=False)
                self.ensure_measured(self.path, again=True)          # what is left is measured again
            # "seq time path": the other panes measure again only what is under or above that path
            self.my_stamp = disksrc.say_changed(r["path"])
            nxt = getattr(self, "after_delete", None)
            if nxt:
                self.cur_id = self.sel_id = nxt
                self.touched = True
                self.after_delete = None

    def forget(self, r):
        """Take what was deleted out of the measures, so the sizes above it are right at once."""
        size = r["size"] or 0
        pre = r["path"].rstrip("/") + "/"
        # a du still measuring there prints the folders above last, with what was deleted still in
        # them: measure again instead of fixing totals du is about to write over
        if any(not m.done and not m.cancelled and m.covers(os.path.dirname(r["path"]) or "/") for m in self.measures):
            self.listing.clear()
            self.ensure_measured(self.path, again=True)
            return
        for m in self.measures:
            for p in [p for p in list(m.sizes) if p == r["path"] or p.startswith(pre)]:
                m.sizes.pop(p, None)
            parent = os.path.dirname(r["path"])
            while True:
                if parent in m.sizes:
                    m.sizes[parent] = max(0, m.sizes[parent] - size)
                if parent in ("/", "") or parent == m.root:
                    break
                parent = os.path.dirname(parent)

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash(f"copied: {disksrc.short(text, 60)}")


if __name__ == "__main__":
    run(Folders)
