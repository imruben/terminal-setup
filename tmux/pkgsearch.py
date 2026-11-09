#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Search pane of the `packages` tab · every package of every source
#    apt   apt-cache search (names and descriptions), at once
#    snap  the Snap Store (needs internet, ~1 s)
#    brew  Homebrew's formula catalogue
#  Several words must all match. Best name matches first; installed ones show
#  their version. apt answers at once, snap and brew join when they answer.
#
#  Right-click: install / uninstall (ask first; apt and snap ask for your password
#  in a popup; classic snaps get --classic) · details (Package pane) · copy the name.
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
from tui import DIM, GREEN, SUB, TEXT, YELLOW

ICON = dict(add="\U000F01DA", remove="\U000F0A7A", info="\U000F02FD", copy="\U000F018F")
LIMIT = 400                                     # rows per source
KEEP_QUERIES = 6                                # the answers of the last few searches are kept, older ones go
ORDER = {"apt": 0, "snap": 1, "brew": 2}


class Search(SourcesPane, TableApp):
    icon = "\U000F0349"
    master = True
    title = "Search"
    noun = "found"
    interval = 1.0
    reload_every = float("inf")                 # it searches when the words change, not on a timer
    remote_query = True
    sort_key = "rank"
    columns = [Column("name", "PACKAGE", 24, min=12),
               Column("src", "FROM", 4),
               Column("installed", "INSTALLED", 14, min=9),
               Column("why", "WHY", 24, optional=True),
               Column("desc", "DESCRIPTION", optional=True)]

    def __init__(self, screen):
        self.start_sources()
        self.pending = False
        self.truncated = set()
        self.recent = []                            # the last searches, newest last (their answers are kept)
        super().__init__(screen)

    def fetch(self):
        words = self.query.lower().split()
        self.truncated = set()
        if not words or len(" ".join(words)) < 2:
            return []
        q, rows, notes = words[0], [], read_notes()
        key = tuple(words)
        if key in self.recent:
            self.recent.remove(key)
        self.recent.append(key)
        for old in self.recent[:-KEEP_QUERIES]:     # memory: only the last few searches' answers stay
            for s in pkgsrc.sources():
                self.bg.drop((s.name, "search", old))
        self.recent = self.recent[-KEEP_QUERIES:]
        for s in pkgsrc.sources():
            def ask(s=s):
                """In the background: search, rank, keep the best LIMIT, then mark which of those are
                installed (only what is shown is kept: a search for 'li' finds ~70 000)."""
                found = s.search(words)
                for r in found:
                    name = r["name"]
                    r["rank"] = (0 if name == q else 1 if name.startswith(q) else 2 if q in name else 3,
                                 len(name), ORDER.get(s.name, 9), name)
                found.sort(key=lambda r: r["rank"])
                cut = len(found) > LIMIT
                found = found[:LIMIT]
                if s.name == "apt":
                    s.mark_installed(found)
                return {"rows": found, "cut": cut}
            # every source in the background (apt-cache too): typing never waits · the same words
            # are not asked twice for 10 min
            got = self.bg.get((s.name, "search", key), ask, 600) or {"rows": [], "cut": False}
            found = [dict(r) for r in got["rows"]]
            if got["cut"]:
                self.truncated.add(s.name)
            for r in found:
                rows.append({**r, "id": f"{s.name}:{r['name']}", "src": s.name,
                             "why": notes.get(note_key(s.name, r["name"]), "")})
        return rows

    # typing only marks the search as pending; it runs once typing pauses (TYPING_PAUSE), not for
    # every prefix ("postgresql" would start apt, snap and brew searches for p, po, pos…)
    TYPING_PAUSE = 0.35

    def tick_every(self):
        """Fast only while a search waits for typing to pause."""
        return 0.15 if self.visible and self.pending else super().tick_every()

    def on_tick(self):
        if self.pending and time.monotonic() - self.typed_at < self.TYPING_PAUSE:
            return
        if self.changed() or self.pending:
            self.pending = False
            self.reload()

    def dispatch(self, ev):
        kind = ev[0]
        if not (self.menu or self.ask or self.prompt):
            if kind == "char":
                self.query += ev[1]
                self.query_changed()
                self.pending, self.typed_at = True, time.monotonic()
                return
            if kind == "key" and ev[1] in ("backspace", "ctrl-u", "esc"):
                self.query = "" if ev[1] != "backspace" else self.query[:-1]
                self.query_changed()
                self.pending, self.typed_at = True, time.monotonic()
                return
        super().dispatch(ev)

    def summary(self):
        if self.pending:
            return f"{YELLOW}searching…"
        parts = [self.loading_note()] if self.query.strip() else []
        if self.truncated:
            parts.append(f"{YELLOW}first {LIMIT} of {' · '.join(sorted(self.truncated))}: add words to narrow it")
        return f"{DIM} · ".join(p for p in parts if p)

    def footer(self, y):
        if not self.query.strip() and not (self.ask or self.prompt or self.msg):
            names = " · ".join(s.name for s in pkgsrc.sources())
            return f" {DIM}type to search every package ({names}): names and descriptions"
        return super().footer(y)

    def row_colour(self, r):
        return GREEN if r["installed"] else SUB

    def detail(self, r):
        state = f"{GREEN}installed {r['installed']}" if r["installed"] else f"{DIM}not installed"
        why = f" · {YELLOW}why: {r['why']}{DIM}" if r.get("why") else ""
        classic = f" · {YELLOW}classic snap (full access to your system){DIM}" if r.get("classic") else ""
        return f"{TEXT}{r['name']}{DIM} · {r['src']} · {state}{DIM}{why}{classic} · {r['desc']}"

    def selected(self, r):
        if r:
            tmuxlink.publish("@pkg-selected", r["id"])

    def menu_title(self, r):
        return f"{r['name']} · {r['src']}"

    def menu_items(self, r):
        inst = bool(r["installed"])
        return [(f"{ICON['add']}  Install…", "i", None if inst else (lambda: self.ask_install(r))),
                (f"{ICON['remove']}  Uninstall…", "u", (lambda: self.ask_remove(r)) if inst else None),
                ("", "", None),
                (f"{ICON['info']}  Details and files", "d", lambda: tmuxlink.focus("Package")),
                (f"{ICON['copy']}  Copy the name", "c", lambda: self.copy(r["name"]))]

    def how(self, s, what):
        return pkgsrc.how(s, what)

    def ask_install(self, r):
        s = pkgsrc.source(r["src"])
        if s:
            classic = " It is a classic snap: full access to your system, like an apt package." if r.get("classic") else ""
            self.confirm(f"Install {r['name']} ({r['src']})?{self.how(s, 'adds')}{classic}",
                         lambda: pkg_popup(self, f"install · {r['name']} · {r['src']}", s.install(r["name"], r)), r)

    def ask_remove(self, r):
        s = pkgsrc.source(r["src"])
        if s:
            self.confirm(f"Uninstall {r['name']} ({r['src']})?{self.how(s, 'removes')}",
                         lambda: pkg_popup(self, f"uninstall · {r['name']} · {r['src']}", s.remove(r["name"])), r)

    def on_delete(self, r):
        if r["installed"]:
            self.ask_remove(r)

    def copy(self, text):
        if not tmuxlink.copy(text):
            self.flash("could not copy", ok=False)
            return
        self.flash(f"copied: {text}")


if __name__ == "__main__":
    run(Search)
