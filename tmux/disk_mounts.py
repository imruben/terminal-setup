#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Disks pane of the `disk` tab · the filesystems worth looking at (tmux/disksrc.py):
#  used / free / size and how full (yellow from 75%, red from 90%).
#  WSL: the Linux disk and the Windows drives (C:, D:…) · macOS: Macintosh HD and
#  what is plugged in. The pane keeps the height of its list (tmux/system/disk-fit.sh).
#
#  Double-click (or right-click → Show its folders): Folders shows that disk.
#  Right-click: open it with the system's app · copy where it is mounted.
# ═══════════════════════════════════════════════════════════════

import os
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import disksrc
import tmuxlink
from background import Background
from disksrc import bar, human
from table import Column, TableApp, run
from tui import DIM, RED, TEXT, YELLOW

HERE = os.path.dirname(os.path.realpath(__file__))
ICON = dict(folders="\U000F024B", app="\U000F03D6", copy="\U000F018F")


class Disks(TableApp):
    icon = "\U000F02CA"
    title = "Disks"
    noun = "disks"
    interval = 10.0
    sort_key = "order"
    search_keys = ("label", "mount", "type", "device")
    columns = [Column("label", "DISK", 13, min=8),
               Column("pct_txt", "USE", 5, "r", sort="pct", desc=True),
               Column("bar", "", 10, sort="pct_bar", desc=True, optional=True),
               Column("used_txt", "USED", 7, "r", sort="used", desc=True),
               Column("free_txt", "FREE", 7, "r", sort="free", desc=True),
               Column("size_txt", "SIZE", 7, "r", sort="size", desc=True, optional=True),
               Column("mount", "MOUNTED ON", optional=True, min=8),
               Column("type", "TYPE", 6, optional=True)]
    watch = ("@disk-changed",)

    def __init__(self, screen):
        self.rows_seen = None
        self.changed_seen = None
        self.bg = Background(self.wake, fallback=list)
        self.last = []
        super().__init__(screen)

    def fetch(self):
        # df in the background: a network drive that does not answer must not freeze the pane;
        # an empty answer (df timed out) keeps the last good rows
        found = self.bg.get(("reading",), disksrc.mounts, 8) or []
        if found:
            self.last = found
        rows = []
        for n, d in enumerate(self.last):
            pct = d["used"] / (d["used"] + d["free"]) if d["used"] + d["free"] else 0
            rows.append({**d, "id": d["mount"], "pct": pct, "pct_bar": pct, "pct_txt": f"{pct * 100:.0f}%",
                         "bar": bar(pct, 10),
                         "used_txt": human(d["used"]), "free_txt": human(d["free"]), "size_txt": human(d["size"]),
                         "order": n})
        if len(rows) != self.rows_seen:            # keep the pane as tall as its list
            self.rows_seen = len(rows)
            pane = os.environ.get("TMUX_PANE", "")
            if pane:
                tmuxlink.tmux("set", "-p", "-t", pane, "@rows", str(len(rows)))
                subprocess.Popen([os.path.join(HERE, "system", "disk-fit.sh"), pane],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return rows

    def on_tick(self):
        stamp = self.opts.get("@disk-changed")
        if stamp != self.changed_seen:
            self.changed_seen = stamp
            self.bg.forget()
            self.reload()

    def summary(self):
        free = sum(r["free"] for r in self.all if r["mount"] in ("/", "/System/Volumes/Data"))
        if not free:
            return ""
        c = next((r for r in self.all if r["mount"] == "/mnt/c"), None)
        if disksrc.WSL and c and c["free"] < free:      # the WSL disk is a file on C: it cannot outgrow it
            return f"{TEXT}{human(c['free'])} free{DIM} for WSL (what C: has left)"
        return f"{TEXT}{human(free)} free{DIM} on the system disk"

    def row_colour(self, r):
        return RED if r["pct"] >= 0.9 else YELLOW if r["pct"] >= 0.75 else TEXT

    def detail(self, r):
        bits = [f"{TEXT}{r['mount']}{DIM} · {r['device']} · {r['type'] or '?'}"]
        if disksrc.WSL and r["mount"] == "/":
            distro = os.environ.get("WSL_DISTRO_NAME") or "<distro>"
            bits.append(f"space freed here goes back to Windows only if the WSL disk is sparse: "
                        f"wsl --manage {distro} --set-sparse true (in Windows)")
        elif disksrc.WSL and r["type"] == "9p":
            bits.append("a Windows drive: measuring it from Linux is slow")
        return f"{DIM} · ".join(bits)

    def menu_title(self, r):
        return r["label"]

    def menu_items(self, r):
        return [(f"{ICON['folders']}  Show its folders", "o", lambda: self.show(r)),
                (f"{ICON['app']}  Open with the system's app" + (" (Explorer)" if disksrc.WSL else ""), "a",
                 lambda: self.open_app(r)),
                (f"{ICON['copy']}  Copy where it is mounted", "c", lambda: self.copy(r["mount"]))]

    def on_double(self, r, col, x):
        self.show(r)

    def show(self, r):
        tmuxlink.put("@disk-go", r["mount"])
        tmuxlink.focus("Folders")
        if disksrc.WSL and r["type"] == "9p":
            self.flash(f"{r['label']}: a Windows drive, measuring it takes a while")

    def open_app(self, r):
        if tmuxlink.open_url(r["mount"]):
            self.flash(f"opening {r['mount']}")
        else:
            self.flash(f"could not start {tmuxlink.BROWSER}", ok=False)

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash(f"copied: {text}")


if __name__ == "__main__":
    run(Disks)
