"""Width-aware text utilities, wrap, renderer sync, and mouse decoding."""

import contextlib
import io
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


class TestWrap(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(term.wrap("the quick brown fox", 10),
                         ["the quick", "brown fox"])

    def test_ansi_words_keep_codes(self):
        red = "\x1b[31mred\x1b[0m"
        self.assertEqual(term.wrap(red + " blue", 4), [red, "blue"])

    def test_long_word_hard_break(self):
        self.assertEqual(term.wrap("abcdefgh", 3), ["abc", "def", "gh"])

    def test_long_word_after_short(self):
        self.assertEqual(term.wrap("hi abcdefgh", 4), ["hi", "abcd", "efgh"])

    def test_exact_fit(self):
        self.assertEqual(term.wrap("ab cd", 5), ["ab cd"])
        self.assertEqual(term.wrap("abcd", 4), ["abcd"])

    def test_empty_string(self):
        self.assertEqual(term.wrap("", 5), [""])

    def test_nonpositive_width(self):
        self.assertEqual(term.wrap("abc def", 0), ["abc def"])
        self.assertEqual(term.wrap("abc", -3), ["abc"])

    def test_cjk_counted_wide(self):
        self.assertEqual(term.wrap("日日 日", 4), ["日日", "日"])
        self.assertEqual(term.wrap("日日日", 4), ["日日", "日"])

    def test_glyph_wider_than_width_no_blank_line(self):
        self.assertEqual(term.wrap("日", 1), ["日"])
        self.assertEqual(term.wrap("日本", 1), ["日", "本"])

    def test_leading_bare_sgr_code_stays_with_next_word(self):
        self.assertEqual(term.wrap("\x1b[31m hello", 5), ["\x1b[31mhello"])

    def test_no_trailing_spaces(self):
        for line in term.wrap("a  b   c", 3):
            self.assertEqual(line, line.rstrip(" "))


class TestRendererSync(unittest.TestCase):
    def _render(self, renderer, lines, size):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            renderer.render(lines, size)
        return buf.getvalue()

    def test_sync_wraps_output(self):
        out = self._render(term.Renderer(sync=True), ["hi"], (10, 2))
        self.assertIn("\x1b[?2026h", out)
        self.assertIn("\x1b[?2026l", out)
        self.assertLess(out.index("\x1b[?2026h"), out.index("hi"))
        self.assertLess(out.index("hi"), out.index("\x1b[?2026l"))

    def test_no_sync_no_wrapper(self):
        out = self._render(term.Renderer(sync=False), ["hi"], (10, 2))
        self.assertIn("hi", out)
        self.assertNotIn("\x1b[?2026h", out)
        self.assertNotIn("\x1b[?2026l", out)

    def test_no_change_frame_emits_nothing(self):
        r = term.Renderer(sync=True)
        self._render(r, ["hi"], (10, 2))
        out = self._render(r, ["hi"], (10, 2))
        self.assertEqual(out, "")


class TestMouseDecode(unittest.TestCase):
    def _decode(self, body):
        ev = term._decode_csi(b"[", body)
        self.assertIsInstance(ev, term.MouseEvent)
        return ev

    def test_left_press(self):
        ev = self._decode(b"<0;10;5M")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (4, 9, "left", "press"))

    def test_left_release(self):
        ev = self._decode(b"<0;10;5m")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (4, 9, "left", "release"))

    def test_wheel_up(self):
        ev = self._decode(b"<64;1;1M")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (0, 0, "wheel_up", "wheel"))

    def test_wheel_down(self):
        ev = self._decode(b"<65;3;4M")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (3, 2, "wheel_down", "wheel"))

    def test_drag_motion(self):
        ev = self._decode(b"<32;7;8M")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (7, 6, "left", "motion"))

    def test_right_press(self):
        ev = self._decode(b"<2;1;1M")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (0, 0, "right", "press"))

    def test_arrow_keys_still_decode(self):
        self.assertEqual(term._decode_csi(b"[", b"A"), term.Key.UP)
        self.assertEqual(term._decode_csi(b"[", b"5~"), term.Key.PGUP)


if __name__ == "__main__":
    unittest.main()
