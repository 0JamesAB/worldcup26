"""Width-aware text utilities, wrap, renderer sync, and mouse decoding."""

import contextlib
import io
import os
import threading
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


class TestRendererRawLineMemo(unittest.TestCase):
    """The raw-line memo may only SKIP work for unchanged lines: repeated
    frames emit zero bytes, and changed-line transitions emit exactly the
    bytes a fresh (memo-less) Renderer emits for the same transition."""

    def _render(self, renderer, lines, size):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            renderer.render(lines, size)
        return buf.getvalue()

    SIZE = (20, 4)
    FRAME_A = ["\x1b[1mheader\x1b[0m", "alpha", "beta \x1b[31mred\x1b[0m"]
    FRAME_B = ["\x1b[1mheader\x1b[0m", "ALPHA!", "beta \x1b[31mred\x1b[0m"]

    def test_identical_frame_emits_zero_bytes(self):
        r = term.Renderer(sync=True)
        self._render(r, list(self.FRAME_A), self.SIZE)
        out = self._render(r, list(self.FRAME_A), self.SIZE)
        self.assertEqual(out, "")

    def test_changed_line_matches_fresh_renderer_transition(self):
        # Memoized renderer: A, A (no-op), then B with one changed line.
        r = term.Renderer(sync=True)
        self._render(r, list(self.FRAME_A), self.SIZE)
        self._render(r, list(self.FRAME_A), self.SIZE)
        memo_out = self._render(r, list(self.FRAME_B), self.SIZE)

        # Fresh renderer doing the same A -> B transition directly.
        fresh = term.Renderer(sync=True)
        self._render(fresh, list(self.FRAME_A), self.SIZE)
        fresh_out = self._render(fresh, list(self.FRAME_B), self.SIZE)

        self.assertEqual(memo_out, fresh_out)
        # Only the changed row is repainted.
        self.assertIn("ALPHA!", memo_out)
        self.assertNotIn("alpha", memo_out)
        self.assertNotIn("header", memo_out)

    def test_first_frame_bytes_unchanged_by_memo(self):
        # Two fresh renderers painting the same first frame emit identical
        # bytes: the memo never alters a cold start.
        out1 = self._render(term.Renderer(sync=True),
                            list(self.FRAME_A), self.SIZE)
        out2 = self._render(term.Renderer(sync=True),
                            list(self.FRAME_A), self.SIZE)
        self.assertEqual(out1, out2)
        for row in ("header", "alpha", "beta"):
            self.assertIn(row, out1)

    def test_raw_differs_padded_equal_emits_nothing(self):
        # "hi " and "hi" pad to the same 10-column string; the raw memo
        # misses but the padded diff must still suppress the emit.
        r = term.Renderer(sync=True)
        self._render(r, ["hi "], (10, 1))
        out = self._render(r, ["hi"], (10, 1))
        self.assertEqual(out, "")
        # And the padded cache stays valid for the next frame.
        out = self._render(r, ["hi"], (10, 1))
        self.assertEqual(out, "")

    def test_reset_clears_memo_and_repaints_fully(self):
        r = term.Renderer(sync=True)
        self._render(r, list(self.FRAME_A), self.SIZE)
        buf_reset = io.StringIO()
        with contextlib.redirect_stdout(buf_reset):
            r.reset()
        self.assertIn("\x1b[2J", buf_reset.getvalue())
        out = self._render(r, list(self.FRAME_A), self.SIZE)
        for row in ("header", "alpha", "beta"):
            self.assertIn(row, out)

    def test_resize_clears_memo_and_repaints_fully(self):
        r = term.Renderer(sync=True)
        self._render(r, list(self.FRAME_A), self.SIZE)
        out = self._render(r, list(self.FRAME_A), (30, 4))
        for row in ("header", "alpha", "beta"):
            self.assertIn(row, out)

    def test_shorter_lines_list_pads_missing_rows(self):
        r = term.Renderer(sync=True)
        self._render(r, list(self.FRAME_A), self.SIZE)
        out = self._render(r, list(self.FRAME_A[:1]), self.SIZE)
        fresh = term.Renderer(sync=True)
        self._render(fresh, list(self.FRAME_A), self.SIZE)
        fresh_out = self._render(fresh, list(self.FRAME_A[:1]), self.SIZE)
        self.assertEqual(out, fresh_out)
        self.assertNotEqual(out, "")

    def test_sync_wrapper_only_when_bytes_emitted(self):
        r = term.Renderer(sync=True)
        out = self._render(r, list(self.FRAME_A), self.SIZE)
        self.assertIn("\x1b[?2026h", out)
        self.assertIn("\x1b[?2026l", out)
        self.assertEqual(self._render(r, list(self.FRAME_A), self.SIZE), "")


class TestDisplayWidthAsciiFastPath(unittest.TestCase):
    """The isascii() fast path must agree with the per-char slow path."""

    CORPUS = [
        "",
        " ",
        "hello world",
        "0123456789 ~!@#$%^&*()_+-=[]{}|;:'\",.<>/?",
        "tab\tand\nnewline",  # control chars: still ASCII, width by len()
        "\x1b[1mbold ascii\x1b[0m",
        "\x1b[38;2;10;20;30mcolored\x1b[0m plain",
        "日本語",
        "a日b本c",
        "\x1b[31m日\x1b[0m ascii tail",
        "⚽ goal 🎉",
        "café",          # combining acute
        "é́x",      # stacked combining marks
        "mixed 日 ⚽ é end",
        "…ellipsis and — dashes",
    ]

    def _reference_width(self, s):
        return sum(term.char_width(c) for c in term.strip_ansi(s))

    def test_equivalence_over_mixed_corpus(self):
        for s in self.CORPUS:
            self.assertEqual(term.display_width(s), self._reference_width(s),
                             msg=repr(s))

    def test_ascii_width_is_stripped_length(self):
        s = "\x1b[1mplain ascii\x1b[0m"
        self.assertEqual(term.display_width(s), len("plain ascii"))

    def test_char_width_cache_stable(self):
        # lru_cache must not change results across repeated calls.
        for ch in ("a", "日", "⚽", "́", "🎉"):
            first = term.char_width(ch)
            for _ in range(3):
                self.assertEqual(term.char_width(ch), first)


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


class TestSetMouse(unittest.TestCase):
    """set_mouse writes mode sequences and tracks state (no tty entry needed)."""

    def _tw(self):
        tw = term.RawTerminal.__new__(term.RawTerminal)
        tw.mouse = False
        return tw

    def _capture(self, fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return buf.getvalue()

    def test_enable_disable_sequences(self):
        tw = self._tw()
        out = self._capture(lambda: tw.set_mouse(True))
        self.assertIn("\x1b[?1000;1002;1006h", out)
        self.assertTrue(tw.mouse)
        out = self._capture(lambda: tw.set_mouse(False))
        self.assertIn("\x1b[?1006;1002;1000l", out)
        self.assertFalse(tw.mouse)

    def test_noop_when_unchanged(self):
        tw = self._tw()
        self.assertEqual(self._capture(lambda: tw.set_mouse(False)), "")
        self._capture(lambda: tw.set_mouse(True))
        self.assertEqual(self._capture(lambda: tw.set_mouse(True)), "")


class TestReadKey(unittest.TestCase):
    """read_key(fd=...) decoding, driven by byte streams over an os.pipe.

    The write end stays open for the whole test so the pipe behaves like a
    quiet terminal: reads past the written bytes time out instead of EOF."""

    def setUp(self):
        self.r, self.w = os.pipe()

    def tearDown(self):
        for fd in (self.r, self.w):
            try:
                os.close(fd)
            except OSError:
                pass

    def _key(self, data=b"", timeout=0.2):
        if data:
            os.write(self.w, data)
        return term.read_key(timeout=timeout, fd=self.r)

    def test_timeout_returns_none(self):
        self.assertIsNone(self._key(timeout=0.01))

    def test_plain_char(self):
        self.assertEqual(self._key(b"x"), "x")

    def test_reads_one_key_at_a_time(self):
        os.write(self.w, b"ab")
        self.assertEqual(term.read_key(fd=self.r), "a")
        self.assertEqual(term.read_key(fd=self.r), "b")

    def test_enter_tab_backspace(self):
        self.assertEqual(self._key(b"\r"), term.Key.ENTER)
        self.assertEqual(self._key(b"\n"), term.Key.ENTER)
        self.assertEqual(self._key(b"\t"), term.Key.TAB)
        self.assertEqual(self._key(b"\x7f"), term.Key.BACKSPACE)

    def test_ctrl_c_raises(self):
        os.write(self.w, b"\x03")
        with self.assertRaises(KeyboardInterrupt):
            term.read_key(fd=self.r)

    def test_ctrl_letter(self):
        self.assertEqual(self._key(b"\x12"), "CTRL_R")

    def test_arrows_csi(self):
        self.assertEqual(self._key(b"\x1b[A"), term.Key.UP)
        self.assertEqual(self._key(b"\x1b[B"), term.Key.DOWN)
        self.assertEqual(self._key(b"\x1b[C"), term.Key.RIGHT)
        self.assertEqual(self._key(b"\x1b[D"), term.Key.LEFT)

    def test_arrows_ss3(self):
        self.assertEqual(self._key(b"\x1bOA"), term.Key.UP)
        self.assertEqual(self._key(b"\x1bOD"), term.Key.LEFT)

    def test_tilde_sequences(self):
        self.assertEqual(self._key(b"\x1b[5~"), term.Key.PGUP)
        self.assertEqual(self._key(b"\x1b[6~"), term.Key.PGDN)
        self.assertEqual(self._key(b"\x1b[3~"), term.Key.DELETE)

    def test_shift_tab(self):
        self.assertEqual(self._key(b"\x1b[Z"), term.Key.SHIFT_TAB)

    def test_bare_esc_times_out_to_esc(self):
        # Write end stays open, so the 0.02s peek window expires.
        self.assertEqual(self._key(b"\x1b"), term.Key.ESC)

    def test_split_escape_arrives_during_peek_window(self):
        # ESC first; the rest lands while read_key waits in the peek
        # window, so the select wakes on arrival and decodes UP.
        os.write(self.w, b"\x1b")
        t = threading.Timer(0.005, os.write, (self.w, b"[A"))
        t.start()
        try:
            self.assertEqual(term.read_key(fd=self.r), term.Key.UP)
        finally:
            t.cancel()

    def test_split_escape_buffered_before_call(self):
        # Whole sequence already queued when read_key starts: same result.
        os.write(self.w, b"\x1b")
        os.write(self.w, b"[A")
        self.assertEqual(term.read_key(fd=self.r), term.Key.UP)

    def test_mouse_press(self):
        ev = self._key(b"\x1b[<0;10;5M")
        self.assertIsInstance(ev, term.MouseEvent)
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (4, 9, "left", "press"))

    def test_mouse_release(self):
        ev = self._key(b"\x1b[<0;10;5m")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (4, 9, "left", "release"))

    def test_mouse_wheel(self):
        ev = self._key(b"\x1b[<64;1;1M")
        self.assertEqual((ev.row, ev.col, ev.button, ev.kind),
                         (0, 0, "wheel_up", "wheel"))

    def test_utf8_two_byte(self):
        self.assertEqual(self._key("é".encode("utf-8")), "é")

    def test_utf8_three_byte(self):
        self.assertEqual(self._key("€".encode("utf-8")), "€")

    def test_utf8_four_byte(self):
        self.assertEqual(self._key("🎉".encode("utf-8")), "🎉")

    def test_utf8_truncated_returns_none(self):
        # Lead byte only: the 0.01s continuation window expires and the
        # partial buffer fails to decode.
        self.assertIsNone(self._key(b"\xc3"))


if __name__ == "__main__":
    unittest.main()
