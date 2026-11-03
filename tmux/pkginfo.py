#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Package pane of the `packages` tab · follows the package highlighted in
#  Packages, Search or Updates, whatever its source (apt, snap, brew: tmux/pkgsrc.py)
#
#  Info     installed / available version, your note (why you installed it) and
#           what the source knows: section, size, homepage (apt) · publisher,
#           channel, confinement, commands (snap) · license, tap, caveats (brew)
#  Files    what it put on disk (installed packages)
#  Depends  what it needs, and which installed packages need it
#  Answers are kept 5 min, or until a package command or a note changes something
#  (brew is slow to ask).
# ═══════════════════════════════════════════════════════════════

import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pkgsrc
from pkgsrc import note_key, pkgs_changed, read_notes, split_id
from tui import BLUE, BOLD, DIM, RESET, SUB, TEXT, YELLOW
from viewer import BackgroundViewer, run

KEEP = 300               # seconds an answer is reused (also changes made outside these panes show up)


class PkgInfo(BackgroundViewer):
    icon = "\U000F03D7"
    title = "Package"
    option = "@pkg-selected"
    tabs = ["Info", "Files", "Depends"]
    interval = 0.3
    empty = "highlight a package in Packages, Search or Updates"
    watch = ("@pkgs-changed", "@pkgs-notes")

    def __init__(self, screen):
        self.cache = {}
        super().__init__(screen)

    def tick(self):
        super().tick()
        # something was installed / removed: show it as it is now
        notes = self.opts.get("@pkgs-notes")
        if self.visible and (pkgs_changed(self, self.opts.get("@pkgs-changed"))
                             or notes != getattr(self, "_notes_seen", notes)):
            self.cache.clear()
            self._bgv.forget()
            self.reload()
        self._notes_seen = notes

    def compute(self, key, tab, width):            # in a thread (BackgroundViewer): brew and the snap store are slow
        src_name, name = split_id(key)
        src = pkgsrc.source(src_name)
        if not src:
            return [f"  {YELLOW}{src_name} is not available on this machine any more"]
        k = (key, tab, width if tab == "Info" else 0)
        at, lines = self.cache.get(k, (0.0, None))
        if lines is None or time.monotonic() - at > KEEP:
            if len(self.cache) > 200:
                self.cache.clear()
            lines = (self.files(src, name) if tab == "Files" else
                     self.depends(src, name) if tab == "Depends" else
                     src.info(name, width, read_notes().get(note_key(src_name, name))))
            self.cache[k] = (time.monotonic(), lines)
        return lines

    def files(self, src, name):
        paths = src.files(name)
        if paths is None:
            return [f"  {DIM}{name} is not installed: install it to see its files"]
        files = [p for p in paths if not os.path.isdir(p)]
        lines = [f"  {DIM}{len(files)} files{RESET}", ""]
        for p in paths:
            lines.append(f"  {DIM}{p}/" if os.path.isdir(p) else f"  {TEXT}{p}")
        return lines

    def depends(self, src, name):
        deps, rdeps = src.depends(name)
        lines = [f"  {BOLD}{BLUE}Needs{RESET}", ""]
        lines += [f"  {SUB}{d}" for d in deps] or [f"  {DIM}nothing"]
        lines += ["", f"  {BOLD}{BLUE}Needed by (installed){RESET}", ""]
        lines += [f"  {SUB}{d}" for d in rdeps] or [f"  {DIM}nothing installed needs it"]
        return lines


if __name__ == "__main__":
    run(PkgInfo)
