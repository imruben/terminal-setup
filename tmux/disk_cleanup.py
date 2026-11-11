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
STAMP = "tmux set -g @disk-changed \"$(python3 -c 'import time; print(time.time_ns())')\""   # macOS date has no %N
EMPTY = 64 * 1024     # an empty folder still takes a few K: nothing worth cleaning


UNSET = object()


class Cleanup(TableApp):
    icon = "\U000F00E2"
    title = "Cleanup"
    noun = "things"
    interval = 2.0
    sort_key = "size"
    search_keys = ("label", "note", "how")
    columns = [Column("label", "WHAT", min=14),
               Column("size", "SIZE", 7, "r", desc=True, fmt=human),
               Column("note", "WHICH", 19, optional=True),
               Column("how", "HOW", 30, optional=True)]
    watch = ("@disk-changed",)

    def __init__(self, screen):
        self.bg = Background(self.wake, fallback=lambda: (None, ""))
        self.items = None               # what this machine has: looked for when first in sight
        self.changed_seen = UNSET       # the first look only notes the value
        self.my_stamps = set()          # the changes this pane made itself (it measured those already)
        self.last_seq = None            # the last @disk-changed number seen: a jump means some were missed
        super().__init__(screen)

    def fetch(self):
        if self.items is None:
            self.items = {i.id: i for i in disksrc.items()}
        rows = []
        for it in self.items.values():
            got = self.bg.get(("measuring", it.id), it.size_fn, EVERY) or (None, "")
            size, note = got[0], got[1]
            can = got[2] if len(got) > 2 else None     # Docker: unused containers / volumes, even at 0B
            if size is None and it.path and not os.path.exists(it.path) and ("measuring", it.id) not in self.bg.busy:
                continue                         # cleaned away (the folder is gone with it)
            how = ("sudo " if it.sudo and not it.how.startswith("sudo") else "") + it.how
            rows.append({"id": it.id, "label": it.label, "size": size, "note": note, "can": can,
                         "how": how if len(how) < 60 else how[:57] + "…", "item": it})
        return rows

    @staticmethod
    def cleanable(r):
        """Docker says itself whether something is unused (a stopped container can be 8K); for
        the rest, more than an empty folder's few K."""
        return bool(r["can"]) if r["can"] is not None else (r["size"] or 0) >= EMPTY

    def on_tick(self):
        stamp = self.opts.get("@disk-changed")
        if stamp != self.changed_seen:
            first = self.changed_seen is UNSET
            self.changed_seen = stamp
            seq, _ = disksrc.read_changed(stamp)
            mine = stamp in self.my_stamps            # this pane's own clean: in order, measured already
            missed = not mine and seq is not None and self.last_seq is not None and seq != self.last_seq + 1
            self.last_seq = seq                   # a bare time (a popup) starts the count again
            if not first and stamp and not mine:
                self.measure_changed("" if missed else stamp)     # missed some (out of sight): all of them

    def measure_changed(self, stamp):
        """Something changed on disk: "seq time path" (deleted in Folders) → only the items under or
        above that path are measured again · just a time (a popup, `clean`) → all of them."""
        _, path = disksrc.read_changed(stamp)
        path = os.path.realpath(path) if path else ""
        for it in (self.items or {}).values():
            ip = os.path.realpath(it.path) if it.path else ""
            if not path or (ip and (ip == path or ip.startswith(path.rstrip("/") + "/")
                                    or path.startswith(ip.rstrip("/") + "/"))):
                self.bg.forget(("measuring", it.id))
        if not path:
            disksrc.forget_docker()
        self.reload()

    # ─── look ───
    def summary(self):
        total = sum(r["size"] or 0 for r in self.all if (r["size"] or 0) >= EMPTY)
        upto = any(r["note"].startswith("up to") for r in self.all if (r["size"] or 0) >= EMPTY)
        busy = "measuring" in self.bg.loading()
        return ((f"{TEXT}{'up to ' if upto else ''}{human(total)}{DIM} can be freed" if total else "")
                + (f" {YELLOW}· measuring…" if busy else ""))

    def row_colour(self, r):
        if not self.cleanable(r):
            return DIM
        return YELLOW if r["size"] >= 1024 ** 3 else TEXT

    def detail(self, r):
        it = r["item"]
        sudo = f" · {YELLOW}needs your password{DIM}" if it.sudo else ""
        return f"{TEXT}{it.label}{DIM} · {it.why}{sudo} · {it.how}"

    def menu_title(self, r):
        return r["label"]

    # ─── menu ───
    def menu_items(self, r):
        it = r["item"]
        return [(f"{ICON['clean']}  Clean ({human(r['size']) or '?'})…", "c",
                 (lambda: self.ask_clean(r)) if self.cleanable(r) else None),
                (f"{ICON['folder']}  Show its folder", "f", (lambda: self.show(it.path)) if it.path and os.path.isdir(it.path) else None),
                (f"{ICON['copy']}  Copy the command", "k", lambda: self.copy(it.command())),
                ("", "", None)] + self.empty_menu_items()

    def empty_menu_items(self):
        return [(f"{ICON['all']}  Run clean (the shell function)…", "C", self.ask_run_clean),
                (f"{ICON['clean']}  Measure again", "m", self.measure_again)]

    def on_delete(self, r):
        if self.cleanable(r):
            self.ask_clean(r)

    # ─── actions ───
    def ask_clean(self, r):
        it = r["item"]
        size = f" ({'up to ' if r['note'].startswith('up to') else 'about '}{human(r['size'])})" if r["size"] else ""
        warn = f" {it.warn}" if it.warn else ""
        how = " · asks for your password" if it.sudo else ""
        self.confirm(f"Clean {it.label}{size}?{warn}{how}", lambda: self.clean(r), r)

    def clean(self, r):
        it = r["item"]
        cmd = it.command()
        if it.sudo:                         # sudo asks for the password in the popup
            self.popup(f"clean · {it.label}", f"{cmd}; {STAMP}; printf '\\npress Enter'; read -r _", "80%", "60%")
            return
        before = r["size"] or 0

        def done(ok, out):
            self.bg.forget(("measuring", it.id))
            if it.tool == "docker":
                disksrc.forget_docker()
            if ok:
                self.flash(f"{it.label}: " + (f"about {human(before)} freed" if before else "cleaned"))
            else:
                self.flash(f"{it.label}: {(out.strip().splitlines() or ['failed'])[-1][:100]}", ok=False)
            # Docker's items have no folder of their own: where its data lives (with none, every
            # disk pane would measure again whatever it shows, /mnt/c included)
            docker_data = os.path.join(disksrc.HOME, "Library/Containers/com.docker.docker") if disksrc.MACOS \
                else "/var/lib/docker"
            stamp = disksrc.say_changed(it.path or (docker_data if it.tool == "docker" else ""))
            self.my_stamps.add(stamp)                 # this pane measured it already
        self.background(r, "cleaning", ["sh", "-c", cmd], done, timeout=None)

    def ask_run_clean(self):
        what = "apt, the journal, snap, brew and Docker's build cache" if not disksrc.MACOS else "brew and Docker's build cache"
        self.confirm(f"Run clean: {what}? (apt and snap ask for your password)", self.run_clean,
                     self.current() or {"id": None})

    def run_clean(self):
        self.popup("clean", f"zsh -ic clean; {STAMP}; printf '\\npress Enter'; read -r _", "80%", "70%")

    def measure_again(self):
        self.items = None                   # a cache that appeared since shows up too
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
