# ═══════════════════════════════════════════════════════════════
#  Slow answers for the system monitor panes, without freezing them:
#  a pane asks for something, gets what is known now (None at first) and
#  redraws when the fresh answer arrives (packages, disk, ssh, git).
# ═══════════════════════════════════════════════════════════════

import threading
import time

STALE = float("-inf")
RETRY = 15


class Background:
    """get(key, fn, ttl): the last answer for key (None until the first one), asking again
    in a thread once it is older than ttl. on_ready() runs when an answer arrives.
    Keys are tuples: loading() names what is being asked by their first item.
    forget() keeps the last answer on screen but asks again at once; an answer that was
    already on its way when forget() was called counts as stale, so it is asked once more.
    When fn raises (no network, a command that timed out) the last good answer stays and it
    is asked again after RETRY seconds: a failure never shows as "nothing"."""

    def __init__(self, on_ready, fallback=list):
        self.data, self.busy, self.on_ready, self.fallback = {}, set(), on_ready, fallback
        self.gen = {}                            # key → bumped by forget(): answers from before are stale
        self.ttl = {}
        self.lock = threading.Lock()

    def get(self, key, fn, ttl):
        with self.lock:
            value, at = self.data.get(key, (None, STALE))
            if key in self.busy or time.monotonic() - at < ttl:
                return value
            self.busy.add(key)
            self.ttl[key] = ttl
            gen = self.gen.get(key, 0)

        def work():
            failed = False
            try:
                result = fn()
            except Exception:                    # a source failing must not take the pane down
                result, failed = self.fallback(), True
            with self.lock:
                fresh = self.gen.get(key, 0) == gen
                old = self.data.get(key)
                if failed and old is not None:   # keep what was known, ask again soon (at once if forgotten)
                    self.data[key] = (old[0], time.monotonic() - self.ttl.get(key, RETRY) + RETRY if fresh else STALE)
                else:
                    self.data[key] = (result, (time.monotonic() - (self.ttl.get(key, RETRY) - RETRY if failed else 0))
                                      if fresh else STALE)
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
        """Ask again next time: everything, or only key (the last answer stays until then)."""
        with self.lock:
            keys = list(self.data) + list(self.busy) if key is None else [key]
            for k in keys:
                self.gen[k] = self.gen.get(k, 0) + 1
                if k in self.data:
                    self.data[k] = (self.data[k][0], STALE)

    def drop(self, key=None):
        """Forget the answers themselves (nothing is shown until the new ones come)."""
        with self.lock:
            for k in (list(self.data) if key is None else [key]):
                self.gen[k] = self.gen.get(k, 0) + 1
                self.data.pop(k, None)


def parallel(fn, items, workers=8):
    """[fn(item) for item in items], up to `workers` at a time, in daemon threads (Ctrl+c never
    waits for them, unlike a ThreadPoolExecutor) · an item whose fn raises gives None."""
    items = list(items)
    out = [None] * len(items)
    it = iter(range(len(items)))
    lock = threading.Lock()

    def worker():
        while True:
            with lock:
                i = next(it, None)
            if i is None:
                return
            try:
                out[i] = fn(items[i])
            except Exception:
                out[i] = None
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(workers, len(items)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out
