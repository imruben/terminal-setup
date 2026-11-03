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
STALE = 600            # a measure older than this (seconds) is done again when the folder is shown


def protected(path):
    """Folders the Delete item never offers: /, your home, the ones right under / and mount points."""
    path = path.rstrip("/") or "/"
    return path in ("/", disksrc.HOME, os.path.dirname(disksrc.HOME)) or path.count("/") <= 1 or os.path.ismount(path) \
        or path in ("/System/Volumes/Data", "/Users", "/Applications", "/Library")


UNSET = object()


class Folders(TableApp):
    icon = "\U000F02CA"
    title = "Folders"
    noun = "items"
    interval = 1.0
    reload_every = 2
    sort_key = "size"
    columns = [Column("name_txt", "NAME", sort="name", min=12),
               Column("size", "SIZE", 7, "r", desc=True, fmt=human),
               Column("share", "SHARE", 16, sort="frac", desc=True, min=10),
               Column("mtime_txt", "MODIFIED", 8, "r", sort="mtime", desc=True, optional=True)]
    watch = ("@disk-go", "@disk-changed")

    def __init__(self, screen):
        self.path = disksrc.HOME
        self.measures = []          # newest first: the folders measured so far (each with its sizes)
        self.listing = {}           # folder → (its mtime, entries)
        self.changed_seen = UNSET       # the first look only notes the value
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
        than STALE, or path is another disk mounted inside the measured folder."""
        m = self.measure_for(path)
        if m and not again:
            if not m.done:
                return m                              # still running: its sizes fill in
            fresh = time.time() - m.finished < STALE
            if path in m.sizes and fresh:
                return m
            if path not in m.sizes and not os.path.ismount(path):
                return m                              # unreadable for du: measuring again would not help
        for old in self.measures:
            if not old.done and not old.covers(path):
                old.cancel()                          # measuring somewhere you left: stop it
        m = Measure(path, self.wake)
        self.measures.insert(0, m)
        return m

    def prune(self):
        """Older measures stay as a fallback while a newer one runs, then go."""
        keep = []
        for m in self.measures:
            newer_done = any(n.done and not n.cancelled and n.covers(m.root) for n in keep)
            if not newer_done and not (m.cancelled and m.done and keep):
                keep.append(m)
        self.measures = keep[:12]

    def size_of(self, path):
        """(bytes or None, measure) of a folder from the newest measure that has it."""
        for m in self.measures:
            if path in m.sizes:
                return m.sizes[path], m
        return None, self.measure_for(path)

    # ─── reading ───
    def entries(self, path):
        try:
            mt = os.stat(path).st_mtime
        except OSError:
            return None
        cached = self.listing.get(path)
        if cached and cached[0] == mt:
            return cached[1]
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
        self.listing[path] = (mt, out)
        return out

    def fetch(self):
        path = self.path
        self.prune()
        m = self.ensure_measured(path)
        found = self.entries(path)
        if found is None:
            self.error = f"cannot read {tilde(path)}"
            found = []
        else:
            self.error = ""
        rows, total = [], 0
        for name, full, st in found:
            is_dir = stat.S_ISDIR(st.st_mode)
            is_link = stat.S_ISLNK(st.st_mode)
            if is_dir:
                size, _ = self.size_of(full)
                other_disk = size is None and m.done and os.path.ismount(full)
            else:
                size = st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size     # on disk, like du
                other_disk = False
            total += size or 0
            icon = ICON["link"] if is_link else ICON["dir"] if is_dir else ICON["file"]
            rows.append({"id": full, "name": name, "name_txt": f"{icon} {name}{'/' if is_dir else ''}",
                         "path": full, "dir": is_dir, "link": is_link, "size": size, "mtime": st.st_mtime,
                         "mtime_txt": ago(st.st_mtime), "other_disk": other_disk,
                         "partial": is_dir and m.partial(full)})
        own, _ = self.size_of(path)
        self.total = own if own else total
        for r in rows:
            frac = (r["size"] or 0) / self.total if self.total else 0
            r["frac"] = frac if r["size"] is not None else None
            r["share"] = (f"{bar(frac, 10)} {frac * 100:3.0f}%" if r["size"] is not None else
                          ("other disk" if r["other_disk"] else "…" if not m.done else "?"))
        if path != "/":
            rows.append({"id": "..", "name": "..", "name_txt": f"{ICON['up']} ..", "path": os.path.dirname(path),
                         "dir": True, "link": False, "size": None, "frac": None, "mtime": None, "mtime_txt": "", "share": "",
                         "other_disk": False, "partial": False})
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
        size = f"{DIM} · {human(self.total)}" if getattr(self, "total", 0) else ""
        if m and not m.done:
            return f"{where}{size}{DIM} · {YELLOW}measuring… {m.count:,} folders"
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
        bits = [f"{TEXT}{tilde(r['path'])}"]
        if r["link"]:
            try:
                bits.append(f"{DIM}→ {os.readlink(r['path'])}")
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
        if getattr(self, "error", "") and not (self.ask or self.prompt or self.msg):
            return f" {RED}{self.error}"
        return super().footer(y)

    def menu_title(self, r):
        return r["name"]

    # ─── moving around ───
    def go(self, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            self.flash(f"{tilde(path)} is not a folder", ok=False)
            return
        came_from = self.path
        self.path = path
        self.query = ""
        self.jump, self.touched, self.top = True, False, 0
        self.reload()
        if os.path.dirname(came_from) == path:          # going up: stay on the folder you came from
            self.cur_id = self.sel_id = came_from
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
            if not first and stamp:                     # something was cleaned: measure again
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
            return [(f"{ICON['up']}  Up to {tilde(r['path'])}", "u", self.up)]
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
                (f"{ICON['term']}  Terminal session in {tilde(self.path)}", "S", lambda: self.session(self.path)),
                (f"{ICON['home']}  Go to your home", "h", (lambda: self.go(disksrc.HOME)) if self.path != disksrc.HOME else None)]

    def on_delete(self, r):
        if r["id"] != ".." and not protected(r["path"]):
            self.ask_delete(r)

    # ─── actions ───
    def measure_again(self):
        self.listing.clear()
        self.ensure_measured(self.path, again=True)
        self.flash(f"measuring {tilde(self.path)} again…")

    def open_app(self, r):
        if tmuxlink.open_url(r["path"]):
            self.flash(f"opening {tilde(r['path'])}")
        else:
            self.flash(f"could not start {tmuxlink.BROWSER}", ok=False)

    def session(self, path):
        name = os.path.basename(path.rstrip("/")) or "root"
        subprocess.Popen([os.path.join(HERE, "terminal.zsh"), "open", name, path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.flash(f"session {name} in {tilde(path)}")

    def ask_delete(self, r):
        size = f" ({human(r['size'])})" if r["size"] else ""
        what = "the folder" if r["dir"] and not r["link"] else "the link" if r["link"] else "the file"
        self.confirm(f"Delete {what} {disksrc.short(r['path'], 50)}{size}? It does not go to a trash: there is no undo",
                     lambda: self.delete(r), r)

    def delete(self, r):
        def done(ok, out):
            if ok:
                self.forget(r)
                self.flash(f"deleted {disksrc.short(r['path'], 50)}" + (f" · {human(r['size'])} freed" if r["size"] else ""))
                tmuxlink.put("@disk-changed", str(time.time_ns()))
            else:
                self.flash(f"could not delete it all: {(out.strip().splitlines() or ['?'])[-1][:100]}", ok=False)
                self.listing.clear()
        argv = ["rm", "-rf", "--", r["path"]] if r["dir"] and not r["link"] else ["rm", "-f", "--", r["path"]]
        self.background(r, "deleting", argv, done)

    def forget(self, r):
        """Take what was deleted out of the measures, so the sizes above it are right at once."""
        size = r["size"] or 0
        pre = r["path"].rstrip("/") + "/"
        for m in self.measures:
            for p in [p for p in m.sizes if p == r["path"] or p.startswith(pre)]:
                del m.sizes[p]
            parent = os.path.dirname(r["path"])
            while True:
                if parent in m.sizes:
                    m.sizes[parent] = max(0, m.sizes[parent] - size)
                if parent in ("/", "") or parent == m.root:
                    break
                parent = os.path.dirname(parent)
        self.listing.pop(os.path.dirname(r["path"]), None)

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash(f"copied: {text}")


if __name__ == "__main__":
    run(Folders)
