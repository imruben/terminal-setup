# What every pane draws with (tmux/tui.py): widths, cutting to a width, wrapping, colours.
# A wrong width here means rows that wrap or leave junk on screen.
import random
import unittest

from helpers import plain
from tui import cut, cw, ellipsis, highlight, keep_bg, pad, vlen, wrap

RED, RESET = "\x1b[31m", "\x1b[0m"


def slow_cut(s, n):
    """The plain text cut() should keep, one character at a time (no ASCII shortcuts): the
    reference the fast version is checked against."""
    out, vis, prev = [], 0, 0
    for ch in plain(s):
        ch = " " if ch == "\t" else "?" if ch < " " or ch == "\x7f" else ch
        w = 1 if ch == "️" and prev == 1 else cw(ch)
        if vis + w > n:
            break
        out.append(ch)
        vis += w
        prev = w if ch != "️" else 0
    return "".join(out)


class Width(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(vlen("hello"), 5)
        self.assertEqual(vlen(RED + "hello" + RESET), 5)

    def test_wide_and_zero_width(self):
        self.assertEqual(vlen("日本"), 4)
        self.assertEqual(vlen("é"), 1)             # combining accent
        self.assertEqual(vlen("a‍b"), 2)            # zero-width joiner

    def test_emoji_presentation(self):
        self.assertEqual(vlen("❤️"), 2)                  # made wide by U+FE0F, as tmux draws it
        self.assertEqual(vlen("✔️x"), 3)
        self.assertEqual(vlen("1️⃣"), 2)                 # keycap: two cells, not three

    def test_links_take_no_room(self):
        self.assertEqual(vlen("\x1b]8;;https://x.y\x1b\\link\x1b]8;;\x1b\\"), 4)


class Cut(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(cut("hello", 3), "hel")
        self.assertEqual(cut("hello", 0), "")
        self.assertEqual(cut("hello", -2), "")
        self.assertEqual(cut("hi", 10), "hi")

    def test_keeps_colours(self):
        self.assertEqual(cut("ab" + RED + "cdef" + RESET, 3), "ab" + RED + "c" + RESET)

    def test_wide_character_that_does_not_fit_ends_it(self):
        self.assertEqual(cut("日本語", 3), "日")
        self.assertEqual(cut("a日", 2), "a")

    def test_controls(self):
        self.assertEqual(cut("a\tb\x01", 9), "a b?")
        self.assertEqual(cut("é\tx\x7f", 9), "é x?")

    def test_column_moves(self):
        self.assertEqual(cut("\x1b[5Gab", 6), "\x1b[5Gab")
        self.assertEqual(cut("ab\x1b[9Gcd", 5), "ab")         # the column is past the end
        self.assertEqual(cut("ab\x1b[2Acd", 9), "abcd")       # a move to another row is dropped

    def test_against_reference(self):
        """Random mixes of ASCII, wide, combining, emoji, controls and codes: never wider than
        asked, and the same text as the one-character-at-a-time reference."""
        rnd = random.Random(7)
        parts = ["a", "bc", " ", "日", "é", "é", "❤", "️", "\t", "\x01", "✔", "\U000F0331",
                 RED, RESET, "\x1b[2K", "\x1b]8;;u\x1b\\", "xyz123", "😀"]
        for _ in range(20000):
            s = "".join(rnd.choice(parts) for _ in range(rnd.randint(0, 12)))
            n = rnd.randint(0, 14)
            got = cut(s, n)
            self.assertLessEqual(vlen(got), n, repr((s, n, got)))
            self.assertEqual(plain(got), slow_cut(s, n), repr((s, n)))

    def test_pad_and_ellipsis(self):
        self.assertEqual(pad("ab", 4), "ab  ")
        self.assertEqual(pad("ab", 4, right=True), "  ab")
        self.assertEqual(ellipsis("hello", 3), "he…")
        self.assertEqual(ellipsis("hi", 3), "hi")
        self.assertEqual(ellipsis("hello", 0), "")


class Wrap(unittest.TestCase):
    def test_short_line_stays(self):
        self.assertEqual(wrap("short", 20), ["short"])

    def test_at_spaces_with_indent(self):
        self.assertEqual(wrap("hello world this is a long line", 12), ["hello world", "  this is a", "  long line"])

    def test_keeps_colour_on_continuations(self):
        self.assertEqual(wrap(RED + "hello world this is a long line", 12),
                         [RED + "hello world", "  " + RED + "this is a", "  " + RED + "long line"])

    def test_long_word_splits(self):
        pieces = wrap("x" * 30, 10)
        self.assertTrue(all(vlen(p) <= 10 for p in pieces))
        self.assertEqual("".join(p.strip() for p in pieces), "x" * 30)

    def test_never_wider(self):
        rnd = random.Random(3)
        words = ["a", "word", "日本", "longerword", "❤️", RED, RESET, "é"]
        for _ in range(3000):
            line = " ".join(rnd.choice(words) for _ in range(rnd.randint(1, 20)))
            width = rnd.randint(4, 30)
            for piece in wrap(line, width):
                self.assertLessEqual(vlen(piece), width, repr((line, width, piece)))


class Background(unittest.TestCase):
    def test_put_back_after_resets(self):
        self.assertEqual(keep_bg("a\x1b[0mb", "BG"), "a\x1b[0mBGb")
        self.assertEqual(keep_bg("a\x1b[mb", "BG"), "a\x1b[mBGb")
        self.assertEqual(keep_bg("a\x1b[49mb", "BG"), "a\x1b[49mBGb")

    def test_colour_numbers_are_not_resets(self):
        self.assertEqual(keep_bg("\x1b[38;5;0mc", "BG"), "\x1b[38;5;0mc")
        self.assertEqual(keep_bg("\x1b[38;2;0;0;0mc", "BG"), "\x1b[38;2;0;0;0mc")

    def test_highlight_fills_the_row(self):
        self.assertEqual(vlen(highlight("abc", 10)), 10)
        self.assertEqual(vlen(highlight("abcdefghijkl", 10)), 10)


if __name__ == "__main__":
    unittest.main()
