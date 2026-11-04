# Keys, mouse and pastes as the panes read them (tmux/tui.py parse, cut_off, coalesce).
import unittest

from helpers import ANSI
from tui import coalesce, cut_off, parse


class Parse(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(list(parse(b"\x1b[A\x1bOB\x1b[5~\r\t\x7f")),
                         [("key", "up"), ("key", "down"), ("key", "pgup"), ("key", "enter"), ("key", "tab"),
                          ("key", "backspace")])

    def test_mouse_press_and_release(self):
        self.assertEqual(list(parse(b"\x1b[<0;5;7M\x1b[<0;5;7m")),
                         [("mouse", 0, 5, 7, False), ("mouse", 0, 5, 7, True)])

    def test_alt_and_utf8(self):
        self.assertEqual(list(parse(b"\x1bx" + "é".encode())), [("key", "alt-x"), ("char", "é")])

    def test_lone_escape(self):
        self.assertEqual(list(parse(b"\x1b")), [("key", "esc")])

    def test_paste_is_one_text(self):
        self.assertEqual(list(parse(b"\x1b[200~hi\nthere\x1b[201~")), [("char", "hi there")])
        self.assertEqual(list(parse(b"\x1b[200~a\r\n")), [("char", "a")])     # no end mark yet

    def test_unknown_sequence_dropped(self):
        self.assertEqual(list(parse(b"\x1b[99;9zq")), [("char", "q")])

    def test_no_codes_left_in_text(self):
        """Whatever arrives mixed up, what comes out as typed text has no escape codes in it."""
        data = b"a\x1b[1;5Cb\x1b[<35;1;2M\x1bOPc\x1b[200~p\x1b[31mq\x1b[201~"
        for ev in parse(data):
            if ev[0] == "char":
                self.assertIsNone(ANSI.search(ev[1]), ev)

    def test_invalid_byte_is_no_key(self):
        self.assertEqual(list(parse(b"\xff")), [])


class Pieces(unittest.TestCase):
    def test_cut_off(self):
        self.assertEqual(cut_off(b"ab\x1b["), 2)              # an escape sequence still arriving
        self.assertEqual(cut_off("é".encode()[:1]), 0)       # half a UTF-8 character
        self.assertIsNone(cut_off(b"abc"))
        self.assertIsNone(cut_off("é".encode()))

    def test_moves_coalesce(self):
        moves = [("mouse", 32, 1, 1, False), ("mouse", 32, 2, 1, False), ("key", "up"), ("mouse", 32, 3, 1, False)]
        self.assertEqual(list(coalesce(moves)),
                         [("mouse", 32, 2, 1, False), ("key", "up"), ("mouse", 32, 3, 1, False)])

    def test_clicks_do_not_coalesce(self):
        clicks = [("mouse", 0, 1, 1, False), ("mouse", 0, 1, 1, True)]
        self.assertEqual(list(coalesce(clicks)), clicks)


if __name__ == "__main__":
    unittest.main()
