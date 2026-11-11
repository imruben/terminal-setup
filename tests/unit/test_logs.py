# The Logs pane's search (tmux/docker_logs.py): it goes on from its last answer (new lines only,
# a longer search within the last matches), so it is checked against filtering from scratch while
# lines arrive, the oldest ones go (the kept log is full) and the search and tab change.
import collections
import random
import threading
import unittest

from helpers import plain
from docker_logs import SEVERITY, Logs


class FakeScreen:
    def size(self):
        return 30, 100

    def poke(self, _):
        pass


def pane(maxlen):
    """A Logs pane without its threads, docker or tmux: only what rebuild() uses."""
    o = Logs.__new__(Logs)
    o.screen, o.lock = FakeScreen(), threading.Lock()
    o.full, o.full_seq, o._pick, o._laid = collections.deque(maxlen=maxlen), 0, None, ({}, None)
    o.tail, o.tab, o.since, o.sel, o.query = collections.deque(maxlen=50), 0, None, None, ""
    o.clamp = lambda: None
    return o


WORDS = ["pay", "payment", "failed", "user", "timeout", "db", "Error", "warn"]
LEVELS = ["info", "warn", "error", "debug"]


class Search(unittest.TestCase):
    def test_same_as_from_scratch(self):
        rnd = random.Random(11)
        o = pane(maxlen=300)
        n = 0
        for step in range(400):
            for _ in range(rnd.choice([0, 0, 1, 3, 40])):           # lines arrive (the oldest go past 300)
                words = " ".join(rnd.choice(WORDS) for _ in range(4))
                e = Logs.entry(f"2026-11-04T10:00:00.{n:09d}Z level={rnd.choice(LEVELS)} msg=\"{words}\" n={n}")
                o.full.append(e)
                o.full_seq += 1
                o.tail.append(e)
                n += 1
            r = rnd.random()
            if r < 0.3 and len(o.query) < 12:                        # typing
                o.query += rnd.choice("payfiledu ")
            elif r < 0.4:
                o.query = o.query[:-1]                               # backspace
            elif r < 0.45:
                o.tab = rnd.randrange(3)
            elif r < 0.5:
                o.query = rnd.choice(["", "pay", "fail", "user db"])
            o.rebuild()
            terms, wanted = o.query.lower().split(), SEVERITY[["All", "Warnings", "Errors"][o.tab]]
            if not o.filtering():
                continue
            want = [e for e in o.full if (not wanted or e[0] in wanted) and all(t in e[2] for t in terms)]
            self.assertEqual(o.matches, len(want), f"step {step}: {o.query!r} tab {o.tab}")
            self.assertEqual(o.entries, want[-2000:], f"step {step}")

    def test_rows_follow_the_entries(self):
        o = pane(maxlen=100)
        for n in range(20):
            e = Logs.entry(f"level=info msg=\"payment {'x' * (n * 7)}\"")
            o.full.append(e)
            o.full_seq += 1
        o.query = "pay"
        o.rebuild()
        o.query = "paym"                                             # laid out again for the new term
        o.rebuild()
        self.assertEqual(len(o.lines), len(o.src))
        self.assertEqual(sorted(set(o.src)), list(range(20)))
        self.assertTrue(all("payment" in plain(o.lines[o.src.index(i)]) for i in range(20)))


if __name__ == "__main__":
    unittest.main()
