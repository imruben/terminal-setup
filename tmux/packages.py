#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Packages tab of the `system` session (tmux/system.sh)
#  The packages you installed yourself, from every source there is (tmux/pkgsrc.py):
#    apt   manual packages minus the base WSL image (~/.apt-base.txt), like the
#          `installed-packages` shell function
#    snap  installed apps (not bases, snapd or content snaps that came as dependencies)
#    brew  formulae installed on request (not their dependencies)
#  with why you installed each one (~/.apt-notes.tsv). The chips on the title row
#  show one source only.
#
#  Right-click a package: why I installed it (edit the note) · details and files
#  (Package pane) · copy the name · uninstall (asks first; apt and snap ask for your
#  password in the popup). The highlighted package is shown in the Package pane.
# ═══════════════════════════════════════════════════════════════

import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pkgsrc
import tmuxlink
from pkgsrc import SourcesPane, human, note_key, pkg_popup, read_notes, write_notes
from table import Column, TableApp, run
from tui import DIM, RESET, SUB, TEXT, YELLOW

ICON = dict(note="\U000F03EB", info="\U000F02FD", files="\U000F0214", copy="\U000F018F", remove="\U000F0A7A")


class Packages(SourcesPane, TableApp):
    icon = "\U000F03D7"
    master = True
    title = "Packages"
    noun = "installed by you"
    interval = 1.0                  # notices a package command at once
    reload_every = 60
    sort_key = "name"
    columns = [Column("name", "PACKAGE", 22, min=12),
               Column("src", "FROM", 4),
               Column("why", "WHY", 34, min=16),
               Column("size", "SIZE", 7, "r", desc=True, fmt=human, optional=True),
               Column("desc", "DESCRIPTION", optional=True)]

    def __init__(self, screen):
        self.start_sources()
        self.error = ""
        super().__init__(screen)

    def fetch(self):
        notes, rows, self.error = read_notes(), [], ""
        for s in pkgsrc.sources():
            if s.name in ("brew", "snap"):          # slow (brew) or may not answer (snapd starting): in the background
                found = self.bg.get((s.name, "mine"), s.mine, 60) or []
            else:
                try:
                    found = s.mine()
                except OSError:                     # one source failing never empties the others
                    found = []
                self.error = self.error or s.error
            for p in found:
                rows.append({**p, "id": f"{s.name}:{p['name']}", "src": s.name,
                             "why": notes.get(note_key(s.name, p["name"]), "")})
        return rows

    def summary(self):
        apt = pkgsrc.source("apt")
        base = f"{YELLOW}no base list: all manual apt shown{RESET}" if apt and apt.error else ""
        return " · ".join(t for t in (base, self.loading_note()) if t)

    def row_colour(self, r):
        return TEXT if r["why"] else SUB

    def detail(self, r):
        why = f"{YELLOW}why: {r['why']}{DIM} · " if r["why"] else f"{DIM}no note yet (right-click → Why…) · "
        apt = pkgsrc.source("apt")
        base = f" · {apt.base_count} apt ones in the base image" if apt and apt.base_count else ""
        return (f"{why}{DIM}{r['src']} {r.get('version', '')} · {len(self.all)} packages · "
                f"{sum(1 for x in self.all if x['why'])} with notes{base}")


    def menu_title(self, r):
        return f"{r['name']} · {r['src']}"

    def menu_items(self, r):
        return [(f"{ICON['note']}  Why I installed it…", "w", lambda: self.edit_note(r)),
                (f"{ICON['info']}  Details and files", "i", lambda: tmuxlink.focus("Package")),
                (f"{ICON['copy']}  Copy the name", "c", lambda: self.copy(r["name"])),
                ("", "", None),
                (f"{ICON['remove']}  Uninstall…", "u", lambda: self.ask_remove(r))]

    def on_delete(self, r):
        self.ask_remove(r)

    def selected(self, r):
        if r:
            tmuxlink.put("@pkg-selected", r["id"])

    def on_tick(self):
        if self.changed():                         # a package command ran in a popup: re-read
            self.reload()

    def edit_note(self, r):
        key = note_key(r["src"], r["name"])

        def save(text):
            notes = read_notes()
            if text:
                notes[key] = text.replace("\t", " ")
            else:
                notes.pop(key, None)
            write_notes(notes)
            tmuxlink.put("@pkgs-notes", str(time.time_ns()))       # the other panes show it (no source asked again)
            self.flash(f"note saved for {r['name']}" if text else f"note removed for {r['name']}")
            self.reload()
        self.ask_text(f"Why is {r['name']} installed?", r["why"], save)

    def ask_remove(self, r):
        s = pkgsrc.source(r["src"])
        if not s:
            return
        self.confirm(f"Uninstall {r['name']} ({r['src']})?{pkgsrc.how(s, 'removes')}",
                     lambda: pkg_popup(self, f"uninstall · {r['name']} · {r['src']}", s.remove(r["name"])), r)

    def copy(self, text):
        self.flash(f"copied: {text}" if tmuxlink.copy(text) else "could not copy", ok=True)


if __name__ == "__main__":
    run(Packages)
