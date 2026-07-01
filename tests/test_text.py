"""Width-aware text utilities."""

import unittest

from tui import term


class TestStripAnsi(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(term.strip_ansi("hello"), "hello")

    def test_sgr_removed(self):
        s = "\x1b[38;2;1;2;3mhi\x1b[0m"
        self.assertEqual(term.strip_ansi(s), "hi")


class TestCharWidth(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(term.char_width("a"), 1)

    def test_cjk_wide(self):
        self.assertEqual(term.char_width("日"), 2)

    def test_emoji_wide(self):
        self.assertEqual(term.char_width("⚽"), 2)
        self.assertEqual(term.char_width("🎉"), 2)

    def test_combining_zero(self):
        self.assertEqual(term.char_width("́"), 0)  # combining acute


class TestDisplayWidth(unittest.TestCase):
    def test_ignores_ansi(self):
        s = "\x1b[1mab\x1b[0m"
        self.assertEqual(term.display_width(s), 2)

    def test_mixed(self):
        self.assertEqual(term.display_width("a日b"), 4)


class TestTruncate(unittest.TestCase):
    def test_fits_unchanged(self):
        self.assertEqual(term.truncate("abc", 5), "abc")

    def test_truncates_with_ellipsis(self):
        out = term.truncate("abcdef", 4)
        self.assertTrue(out.endswith("…"))
        self.assertEqual(term.display_width(out), 4)

    def test_keeps_sgr_and_resets(self):
        s = "\x1b[1m" + "abcdef"
        out = term.truncate(s, 4)
        self.assertIn("\x1b[1m", out)
        self.assertIn(term.RESET, out)

    def test_wide_chars_respected(self):
        out = term.truncate("日日日", 4)
        self.assertLessEqual(term.display_width(out), 4)


class TestPad(unittest.TestCase):
    def test_left(self):
        self.assertEqual(term.pad("ab", 5), "ab   ")

    def test_right(self):
        self.assertEqual(term.pad("ab", 5, align="right"), "   ab")

    def test_center(self):
        self.assertEqual(term.pad("ab", 6, align="center"), "  ab  ")

    def test_colored_string_pads_by_visible_width(self):
        s = "\x1b[1mab\x1b[0m"
        self.assertEqual(term.display_width(term.pad(s, 5)), 5)

    def test_too_long_truncates(self):
        self.assertEqual(term.display_width(term.pad("abcdef", 4)), 4)


if __name__ == "__main__":
    unittest.main()
