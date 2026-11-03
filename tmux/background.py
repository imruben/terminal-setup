# ═══════════════════════════════════════════════════════════════
#  Slow answers for the system monitor panes, without freezing them:
#  a pane asks for something, gets what is known now (None at first) and
#  redraws when the fresh answer arrives (packages, disk, ssh, git).
# ═══════════════════════════════════════════════════════════════

import threading
import time


class Background:
    """get(key, fn, ttl): the last answer for key (None until the first one), asking again
    in a thread once it is older than ttl. on_ready() runs when an answer arrives.
    Keys are tuples: loading() names what is being asked by their first item."""

    def __init__(self, on_ready, fallback=list):
        self.data, self.busy, self.on_ready, self.fallback = {}, set(), on_ready, fallback
        self.lock = threading.Lock()

    def get(self, key, fn, ttl):
        with self.lock:
            value, at = self.data.get(key, (None, float("-inf")))
            if key in self.busy or time.monotonic() - at < ttl:
                return value
            self.busy.add(key)

        def work():
            try:
                result = fn()
            except Exception:                    # a source failing must not take the pane down
                result = self.fallback()
            with self.lock:
                self.data[key] = (result, time.monotonic())
                self.busy.discard(key)
            self.on_ready()
        threading.Thread(target=work, daemon=True).start()
        return value

    def peek(self, key):
        """The last answer for key, without asking again."""
        with self.lock:
            return self.data.get(key, (None, 0.0))[0]

    def loading(self):
        with self.lock:
            return {k[0] for k in self.busy}

    def forget(self, key=None):
        """Ask again next time: everything, or only key."""
        with self.lock:
            if key is None:
                self.data.clear()
            else:
                self.data.pop(key, None)
