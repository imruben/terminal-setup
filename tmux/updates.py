#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Updates pane of the `packages` tab · pending updates from every source
#    apt   `apt list --upgradable` · security updates in yellow
#    snap  what the store has newer (snapd also refreshes by itself a few times a day)
#    brew  `brew outdated` (as of the last `brew update`)
#  The title says when apt last checked; the chips show one source only.
#
#  Right-click a row: upgrade it · upgrade everything from that source · check for
#  updates · details. Upgrades ask first; apt and snap ask for your password in a
#  popup. Right-click the empty list to check for updates.
# ═══════════════════════════════════════════════════════════════

import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pkgsrc
import tmuxlink
from pkgsrc import SourcesPane, note_key, pkg_popup, read_notes
from table import Column, TableApp, run
from tui import DIM, SUB, TEXT, YELLOW

ICON = dict(up="\U000F06B0", all="\U000F0B7A", check="\U000F0450", info="\U000F02FD")
ASK_AGAIN = {"apt": 30, "snap": 1800, "brew": 60}   # seconds between background checks (snap asks the store)


def ago(seconds):
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= n:
            return f"{int(seconds // n)}{unit} ago"
    return "just now"


class Updates(SourcesPane, TableApp):
    icon = "\U000F06B0"
    master = True
    title = "Updates"
    noun = "pending"
    interval = 1.0                  # notices a package command at once
    reload_every = 30
    sort_key = "order"
    columns = [Column("name", "PACKAGE", 22, min=12),
               Column("src", "FROM", 4),
               Column("old", "INSTALLED", 16),
               Column("new", "AVAILABLE", 16),
               Column("why", "WHY", 24, optional=True),
               Column("origin", "CHANNEL", optional=True)]

    def __init__(self, screen):
        self.start_sources()
        super().__init__(screen)

    def fetch(self):
        rows, notes = [], read_notes()
        for s in pkgsrc.sources():
            found = self.bg.get((s.name, "updates"), s.updates, ASK_AGAIN[s.name]) or []    # never on the UI thread
            for u in found:
                held = u.get("held", False)
                rows.append({**u, "id": f"{s.name}:{u['name']}", "src": s.name, "held": held,
                             "origin": ("held · " if held and u["origin"] != "pinned" else "") + u["origin"],
                             "why": notes.get(note_key(s.name, u["name"]), ""),
                             "order": (held, not u["security"], u["name"])})
        return rows

    def on_tick(self):
        if self.changed():
            self.reload()

    def summary(self):
        checked = []
        for s in pkgsrc.sources():                # when each source last looked for updates
            stamp = s.checked()
            if s.name in ("apt", "brew") or stamp:
                checked.append(f"{s.name} {ago(time.time() - stamp) if stamp else 'never checked'}")
        sec = sum(1 for r in self.all if r["security"] and not r["held"])
        held = sum(1 for r in self.all if r["held"])
        loading = self.loading_note()
        return ((f"{YELLOW}{sec} security{DIM} · " if sec else "") + (f"{DIM}{held} held · " if held else "")
                + f"{DIM}{' · '.join(checked)}" + (f"{DIM} · {loading}" if loading else ""))

    def footer(self, y):
        if not self.all and not (self.ask or self.prompt or self.msg):
            if self.bg.loading():
                return f" {DIM}checking for updates…"
            return f" {DIM}everything is up to date · right-click to check for updates"
        return super().footer(y)

    def row_colour(self, r):
        if r["held"]:
            return DIM
        return YELLOW if r["security"] else SUB

    def detail(self, r):
        why = (" · held: apt-mark unhold it to upgrade" if r["src"] == "apt" else " · pinned: brew unpin it to upgrade") \
            if r["held"] else ""
        return f"{TEXT}{r['name']}{DIM} {r['old']} → {TEXT}{r['new']}{DIM} · {r['src']} · {r['origin']}{why}"

    def selected(self, r):
        if r:
            tmuxlink.put("@pkg-selected", r["id"])

    def menu_title(self, r):
        return f"{r['name']} · {r['src']}"

    def of(self, src):
        """What 'upgrade everything' upgrades from src (not what is held or pinned)."""
        return [x for x in self.all if x["src"] == src and not x["held"]]

    def menu_items(self, r):
        s = pkgsrc.source(r["src"])
        if not s:
            return []
        n = len(self.of(r["src"]))
        return [(f"{ICON['up']}  Upgrade {r['name']}…" + ("  (held)" if r["held"] else ""), "u", None if r["held"] else
                 lambda: self.confirm(
                    f"Upgrade {r['name']} {r['old']} → {r['new']}?",
                    lambda: pkg_popup(self, f"upgrade · {r['name']} · {r['src']}", s.upgrade(r["name"])), r)),
                (f"{ICON['all']}  Upgrade everything from {r['src']} ({n})…", "a", (lambda: self.ask_all(s, r)) if n else None),
                ("", "", None)] + self.check_items() + \
               [(f"{ICON['info']}  Details", "d", lambda: tmuxlink.focus("Package"))]

    def check_items(self):
        keys = {"apt": "c", "snap": "s", "brew": "b"}
        return [(f"{ICON['check']}  Check for updates · {s.name}", keys.get(s.name, ""),
                 lambda s=s: pkg_popup(self, f"check for updates · {s.name}", s.check())) for s in pkgsrc.sources()]

    def empty_menu_items(self):
        items = self.check_items()
        for s in pkgsrc.sources():
            n = len(self.of(s.name))
            if n:                                   # (nothing to upgrade when all of it is held)
                items.append((f"{ICON['all']}  Upgrade everything from {s.name} ({n})…", "",
                              lambda s=s: self.ask_all(s, None)))
        return items

    def ask_all(self, s, r):
        """Always asks first: snap and brew start upgrading at once (apt shows its list and asks again)."""
        n = len(self.of(s.name))
        extra = " apt shows the list and asks again" if s.name == "apt" else ""
        self.confirm(f"Upgrade all {n} {s.name} packages?{extra}",
                     lambda: pkg_popup(self, f"upgrade everything · {s.name}", s.upgrade_all()), r or {"id": None})

if __name__ == "__main__":
    run(Updates)
