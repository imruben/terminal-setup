#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Cleanup pane of the `disk` tab · what can be freed on this machine and how
#  (tmux/disksrc.py): apt, the journal, snap, Homebrew, Docker (build cache, unused
#  images, stopped containers, unused volumes), language caches (pip, npm, yarn,
#  pnpm, Composer, Go…), old Claude Code versions, the trash, tmux logs.
#  Only what this machine has shows; sizes are measured in the background (every 5 min).
#
#  Right-click (or Del): clean it (asks first, says how much and what it means;
#  what needs sudo runs in a popup that asks for your password) · show its folder
#  · copy the command · run `clean` (the shell function: apt, journal, snap, brew,
#  Docker build cache) in a popup.
# ═══════════════════════════════════════════════════════════════

import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import disksrc
import tmuxlink
from background import Background
from disksrc import human
from table import Column, TableApp, run
from tui import DIM, TEXT, YELLOW

ICON = dict(clean="\U000F00E2", folder="\U000F024B", copy="\U000F018F", all="\U000F0E1E")
EVERY = 300
EMPTY = 64 * 1024     # an empty folder still takes a few K: nothing worth cleaning


UNSET = object()


class Cleanup(TableApp):
    icon = "\U000F00E2"
    title = "Cleanup"
    noun = "things"
    interval = 2.0
    sort_key = "size"
    columns = [Column("label", "WHAT", min=14),
               Column("size", "SIZE", 7, "r", desc=True, fmt=human),
               Column("note", "WHICH", 19, optional=True),
               Column("how", "HOW", 30, optional=True)]
    watch = ("@disk-changed",)

    def __init__(self, screen):
        self.bg = Background(self.wake, fallback=lambda: (None, ""))
        self.items = {i.id: i for i in disksrc.items()}
        self.changed_seen = UNSET       # the first look only notes the value
        super().__init__(screen)

    def fetch(self):
        rows = []
        for it in self.items.values():
            size, note = self.bg.get(("measuring", it.id), it.size_fn, EVERY) or (None, "")
            if size is None and it.path and not os.path.exists(it.path) and ("measuring", it.id) not in self.bg.busy:
                continue                         # cleaned away (the folder is gone with it)
            rows.append({"id": it.id, "label": it.label, "size": size, "note": note,
                         "how": it.cmd if len(it.cmd) < 60 else it.cmd[:57] + "…", "item": it})
        return rows

    def on_tick(self):
        stamp = self.opts.get("@disk-changed")
        if stamp != self.changed_seen:
            first = self.changed_seen is UNSET
            self.changed_seen = stamp
            if not first:                        # cleaned from a popup or another pane: measure again
                self.bg.forget()
                self.reload()

    # ─── look ───
    def summary(self):
        total = sum(r["size"] or 0 for r in self.all if (r["size"] or 0) >= EMPTY)
        busy = "measuring" in self.bg.loading()
        return (f"{TEXT}{human(total)}{DIM} can be freed" if total else "") + (f" {YELLOW}· measuring…" if busy else "")

    def row_colour(self, r):
        if not r["size"] or r["size"] < EMPTY:
            return DIM
        return YELLOW if r["size"] >= 1024 ** 3 else TEXT

    def detail(self, r):
        it = r["item"]
        sudo = f" · {YELLOW}needs your password{DIM}" if it.sudo else ""
        return f"{TEXT}{it.label}{DIM} · {it.why}{sudo} · {it.cmd}"

    def menu_title(self, r):
        return r["label"]

    # ─── menu ───
    def menu_items(self, r):
        it = r["item"]
        return [(f"{ICON['clean']}  Clean ({human(r['size']) or '?'})…", "c",
                 (lambda: self.ask_clean(r)) if (r["size"] or 0) >= EMPTY else None),
                (f"{ICON['folder']}  Show its folder", "f", (lambda: self.show(it.path)) if it.path and os.path.isdir(it.path) else None),
                (f"{ICON['copy']}  Copy the command", "k", lambda: self.copy(it.cmd)),
                ("", "", None)] + self.empty_menu_items()

    def empty_menu_items(self):
        return [(f"{ICON['all']}  Run clean (apt, journal, snap, brew, Docker build cache)…", "C", self.run_clean),
                (f"{ICON['clean']}  Measure again", "m", self.measure_again)]

    def on_delete(self, r):
        if (r["size"] or 0) >= EMPTY:
            self.ask_clean(r)

    # ─── actions ───
    def ask_clean(self, r):
        it = r["item"]
        warn = f" · {it.warn}" if it.warn else ""
        how = " (asks for your password)" if it.sudo else ""
        self.confirm(f"Clean {it.label}: about {human(r['size'])}{warn}{how}?", lambda: self.clean(r), r)

    def clean(self, r):
        it = r["item"]
        stamp = "tmux set -g @disk-changed \"$(date +%s%N)\""
        if it.sudo:                         # sudo asks for the password in the popup
            self.popup(f"clean · {it.label}", f"{it.cmd}; {stamp}; printf '\\npress Enter'; read -r _", "80%", "60%")
            return
        before = r["size"] or 0

        def done(ok, out):
            self.bg.forget(("measuring", it.id))
            disksrc.forget_docker()
            if ok:
                self.flash(f"{it.label}: about {human(before)} freed")
            else:
                self.flash(f"{it.label}: {(out.strip().splitlines() or ['failed'])[-1][:100]}", ok=False)
            tmuxlink.put("@disk-changed", str(time.time_ns()))
        self.background(r, "cleaning", ["sh", "-c", it.cmd], done)

    def run_clean(self):
        stamp = "tmux set -g @disk-changed \"$(date +%s%N)\""
        self.popup("clean", f"zsh -ic clean; {stamp}; printf '\\npress Enter'; read -r _", "80%", "70%")

    def measure_again(self):
        self.bg.forget()
        disksrc.forget_docker()
        self.flash("measuring again…")
        self.reload()

    def show(self, path):
        tmuxlink.put("@disk-go", path)
        tmuxlink.focus("Folders")

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash("copied the command")


if __name__ == "__main__":
    run(Cleanup)
