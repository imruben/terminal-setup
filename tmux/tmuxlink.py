# ═══════════════════════════════════════════════════════════════
#  How the panes of the `system` session talk to each other:
#  global tmux options (@docker-selected, @pkg-selected, @ports-query…) and
#  focusing a pane by its @label (switching tab if needed).
# ═══════════════════════════════════════════════════════════════

import os
import re
import subprocess
import time


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def get(option):
    return tmux("show", "-gqv", option).stdout.rstrip("\n")


def put(option, value):
    if value is None or value == "":
        tmux("set", "-gu", option)
    else:
        tmux("set", "-g", option, str(value))


def focus(label):
    """Select the pane whose @label is `label` in this session, switching tab if needed."""
    out = tmux("list-panes", "-s", "-F", "#{pane_id}\t#{window_id}\t#{@label}").stdout
    for line in out.splitlines():
        pane, window, lab = line.split("\t")
        if lab == label:
            tmux("select-window", "-t", window)
            tmux("select-pane", "-t", pane)
            return True
    return False


# tmux does not say when the pointer leaves a pane, so every pane of the session notes
# "the pointer is over me" in @pointer while the mouse moves on it (at most every 0.25 s).
# A list only selects the row the pointer rests on if the pointer is still its own.
_LABEL = None
_noted = 0.0


def my_label():
    global _LABEL
    if _LABEL is None:
        pane = os.environ.get("TMUX_PANE", "")
        _LABEL = tmux("display", "-p", "-t", pane, "#{@label}").stdout.strip() if pane else ""
    return _LABEL


def pointer_here(force=False):
    global _noted
    now = time.monotonic()
    if (force or now - _noted >= 0.25) and my_label():
        _noted = now
        put("@pointer", my_label())


def pointer_is_here():
    return bool(my_label()) and get("@pointer") == my_label()


def pane_state(option):
    """(is this pane's window zoomed, value of a global option) in one tmux call."""
    pane = os.environ.get("TMUX_PANE", "")
    fmt = "#{window_zoomed_flag}\t" + ("#{" + option + "}" if option else "")
    out = tmux("display", "-p", *(("-t", pane) if pane else ()), fmt).stdout.rstrip("\n")
    zoomed, _, value = out.partition("\t")
    return zoomed == "1", (value or None)


def pane_view(*options):
    """(zoomed, visible, {option: value or None}) in one tmux call. Visible: someone is
    attached to this session, this pane's tab is the current one and no other pane is zoomed.
    Outside tmux (no answer) it counts as visible, so the pane still works."""
    pane = os.environ.get("TMUX_PANE", "")
    fmt = "\t".join(["#{window_zoomed_flag}",
                     "#{&&:#{&&:#{window_active},#{session_attached}},#{||:#{?window_zoomed_flag,0,1},#{pane_active}}}"]
                    + ["#{" + o + "}" for o in options])
    out = tmux("display", "-p", *(("-t", pane) if pane else ()), fmt).stdout.rstrip("\n")
    if not out:
        return False, True, dict.fromkeys(options)
    zoomed, visible, *values = out.split("\t", 1 + len(options))
    values += [""] * (len(options) - len(values))
    return zoomed == "1", visible == "1", {o: (v or None) for o, v in zip(options, values)}


# Panes out of sight do no work (tmux/table.py, tmux/viewer.py, system/resources.sh): they
# note their pid in the pane option @wake, and tmux sends them SIGUSR1 when their tab comes
# into sight (the hooks in tmux/tmux.conf), so they refresh at once instead of polling.
def note_wake():
    pane = os.environ.get("TMUX_PANE", "")
    if pane:
        tmux("set", "-p", "-t", pane, "@wake", str(os.getpid()))


def forget_wake():
    pane = os.environ.get("TMUX_PANE", "")
    if pane:
        tmux("set", "-pu", "-t", pane, "@wake")


def toggle_zoom():
    pane = os.environ.get("TMUX_PANE", "")
    tmux("resize-pane", "-Z", *(("-t", pane) if pane else ()))


def free_select():
    """Put this pane in tmux copy mode: drag selects any text, only inside this pane;
    releasing copies it and the pane goes back to its program (see MouseDragEnd1Pane)."""
    pane = os.environ.get("TMUX_PANE", "")
    tmux("copy-mode", *(("-t", pane) if pane else ()))
    tmux("display-message", "drag over the text to copy it · q or Esc to leave")


# tmux/system/open.sh opens it with the desktop's browser of each system (Windows' one in
# WSL, `open` on macOS, xdg-open on Linux). TMUX_OPEN_URL replaces it (tests).
BROWSER = os.environ.get("TMUX_OPEN_URL") or os.path.join(os.path.dirname(os.path.realpath(__file__)), "system", "open.sh")


def open_url(url):
    """Open url in the Windows browser; False when that cannot be started."""
    try:
        subprocess.Popen([BROWSER, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def copy(text):
    tmux("set-buffer", "-w", "--", text)


def session_for(path):
    """The session name for a folder (terminal.zsh open): its name (. and : become -), or
    parent-name when a session of that name already works in another folder."""
    def clean(n):
        return re.sub(r"\s+", "-", re.sub(r"[.:]", "-", n.strip())).lstrip("-") or "folder"
    path = path.rstrip("/") or "/"
    name = clean(os.path.basename(path) or "root")
    res = tmux("display", "-p", "-t", f"={name}:", "#{session_path}")
    if res.returncode == 0 and os.path.realpath(res.stdout.strip() or "/") != os.path.realpath(path):
        name = clean(f"{os.path.basename(os.path.dirname(path)) or 'root'}-{os.path.basename(path)}")
    return name
