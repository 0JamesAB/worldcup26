"""Color helpers and depth fallback."""

import os
import unittest
from unittest import mock

from puretui import term


class DepthCase(unittest.TestCase):
    """Save/restore the module color depth around each test."""

    def setUp(self):
        self._saved = term.get_color_depth()

    def tearDown(self):
        term.set_color_depth(self._saved)


class TestRgbTo256(unittest.TestCase):
    def test_grayscale_ends(self):
        self.assertEqual(term._rgb_to_256(0, 0, 0), 16)
        self.assertEqual(term._rgb_to_256(255, 255, 255), 231)

    def test_grayscale_ramp(self):
        self.assertEqual(term._rgb_to_256(128, 128, 128), 232 + round(((128 - 8) / 247) * 24))

    def test_cube_corners(self):
        self.assertEqual(term._rgb_to_256(255, 0, 0), 16 + 36 * 5)
        self.assertEqual(term._rgb_to_256(0, 255, 0), 16 + 6 * 5)
        self.assertEqual(term._rgb_to_256(0, 0, 255), 16 + 5)


class TestFgBgByDepth(DepthCase):
    def test_truecolor(self):
        term.set_color_depth("truecolor")
        self.assertEqual(term.fg(255, 0, 0), "\x1b[38;2;255;0;0m")
        self.assertEqual(term.bg(0, 0, 255), "\x1b[48;2;0;0;255m")

    def test_256(self):
        term.set_color_depth("256")
        self.assertEqual(term.fg(255, 0, 0), f"\x1b[38;5;{16 + 36 * 5}m")

    def test_16_nearest_primaries(self):
        term.set_color_depth("16")
        # Pure red/green are nearest the bright variants (255-based),
        # pure blue is nearest the normal blue (0,0,238).
        self.assertEqual(term.fg(255, 0, 0), "\x1b[91m")
        self.assertEqual(term.fg(0, 255, 0), "\x1b[92m")
        self.assertEqual(term.fg(0, 0, 255), "\x1b[34m")
        self.assertEqual(term.bg(255, 0, 0), "\x1b[101m")
        self.assertEqual(term.bg(0, 0, 255), "\x1b[44m")

    def test_16_black_and_white(self):
        term.set_color_depth("16")
        self.assertEqual(term.fg(0, 0, 0), "\x1b[30m")
        self.assertEqual(term.fg(255, 255, 255), "\x1b[97m")
        self.assertEqual(term.bg(0, 0, 0), "\x1b[40m")
        self.assertEqual(term.bg(255, 255, 255), "\x1b[107m")

    def test_mono_returns_empty(self):
        term.set_color_depth("mono")
        self.assertEqual(term.fg(255, 0, 0), "")
        self.assertEqual(term.bg(255, 0, 0), "")

    def test_clamping(self):
        term.set_color_depth("truecolor")
        self.assertEqual(term.fg(-5, 300, 10), "\x1b[38;2;0;255;10m")

    def test_bad_depth_rejected(self):
        with self.assertRaises(ValueError):
            term.set_color_depth("42")


class TestHexRgb(unittest.TestCase):
    def test_six_digit(self):
        self.assertEqual(term.hex_rgb("#f0c458"), (240, 196, 88))

    def test_three_digit(self):
        self.assertEqual(term.hex_rgb("abc"), (0xAA, 0xBB, 0xCC))

    def test_bad_input(self):
        self.assertIsNone(term.hex_rgb(""))
        self.assertIsNone(term.hex_rgb(None))
        self.assertIsNone(term.hex_rgb("zzzzzz"))
        self.assertIsNone(term.hex_rgb("#12345"))

    def test_fg_hex_fallback(self):
        saved = term.get_color_depth()
        try:
            term.set_color_depth("truecolor")
            self.assertEqual(term.fg_hex("bogus", fallback=(1, 2, 3)),
                             term.fg(1, 2, 3))
        finally:
            term.set_color_depth(saved)


class TestFgBgInterning(DepthCase):
    """fg()/bg() intern their formatted strings per (r, g, b); the cache is
    depth-scoped and must be cleared whenever set_color_depth flips depth."""

    def test_repeat_call_returns_same_object(self):
        term.set_color_depth("truecolor")
        first = term.fg(240, 196, 88)
        self.assertIs(term.fg(240, 196, 88), first)
        firstb = term.bg(10, 20, 30)
        self.assertIs(term.bg(10, 20, 30), firstb)

    def test_cached_value_equals_expected_bytes(self):
        term.set_color_depth("truecolor")
        for _ in range(2):  # second call comes from the cache
            self.assertEqual(term.fg(255, 0, 0), "\x1b[38;2;255;0;0m")
            self.assertEqual(term.bg(0, 0, 255), "\x1b[48;2;0;0;255m")

    def test_clamped_inputs_share_cache_entry(self):
        term.set_color_depth("truecolor")
        self.assertIs(term.fg(-5, 300, 10), term.fg(0, 255, 10))

    def test_depth_flip_changes_output_and_drops_old_cache(self):
        term.set_color_depth("truecolor")
        tc = term.fg(255, 0, 0)
        self.assertEqual(tc, "\x1b[38;2;255;0;0m")
        term.set_color_depth("256")
        v256 = term.fg(255, 0, 0)
        self.assertEqual(v256, f"\x1b[38;5;{16 + 36 * 5}m")
        self.assertNotEqual(v256, tc)
        term.set_color_depth("16")
        self.assertEqual(term.fg(255, 0, 0), "\x1b[91m")
        term.set_color_depth("mono")
        self.assertEqual(term.fg(255, 0, 0), "")
        # And back: no stale entry from any earlier depth survives.
        term.set_color_depth("truecolor")
        self.assertEqual(term.fg(255, 0, 0), "\x1b[38;2;255;0;0m")

    def test_bg_depth_flip_not_reused(self):
        term.set_color_depth("truecolor")
        tc = term.bg(255, 0, 0)
        term.set_color_depth("16")
        self.assertEqual(term.bg(255, 0, 0), "\x1b[101m")
        self.assertNotEqual(term.bg(255, 0, 0), tc)

    def test_set_color_depth_clears_cache_dicts(self):
        term.set_color_depth("truecolor")
        term.fg(1, 2, 3)
        term.bg(4, 5, 6)
        self.assertTrue(term._FG_CACHE)
        self.assertTrue(term._BG_CACHE)
        term.set_color_depth("256")
        self.assertEqual(term._FG_CACHE, {})
        self.assertEqual(term._BG_CACHE, {})

    def test_mono_empty_string_is_cached_correctly(self):
        term.set_color_depth("mono")
        self.assertEqual(term.fg(9, 9, 9), "")
        self.assertEqual(term.fg(9, 9, 9), "")  # cached "" must stay ""
        self.assertEqual(term.bg(9, 9, 9), "")


class TestDetection(unittest.TestCase):
    def test_no_color_forces_mono(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(term._detect_color_depth(), "mono")

    def test_dumb_term_is_mono(self):
        with mock.patch.dict(os.environ, {"TERM": "dumb"}, clear=True):
            self.assertEqual(term._detect_color_depth(), "mono")

    def test_linux_console_is_16(self):
        with mock.patch.dict(os.environ, {"TERM": "linux"}, clear=True):
            self.assertEqual(term._detect_color_depth(), "16")

    def test_vt_term_is_16(self):
        with mock.patch.dict(os.environ, {"TERM": "vt100"}, clear=True):
            self.assertEqual(term._detect_color_depth(), "16")

    def test_colorterm_truecolor(self):
        env = {"COLORTERM": "truecolor", "TERM": "xterm-256color"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(term._detect_color_depth(), "truecolor")

    def test_term_256(self):
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            self.assertEqual(term._detect_color_depth(), "256")

    def test_default_truecolor(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(term._detect_color_depth(), "truecolor")


if __name__ == "__main__":
    unittest.main()
