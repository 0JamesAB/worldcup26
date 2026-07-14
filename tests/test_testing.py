"""Snapshot-testing helpers."""

import re
import unittest

from puretui.canvas import Canvas
from puretui.testing import (plain_lines, render_plain, styled_lines, mask_text,
                         frames_equal, first_diff)


class TestPlainLines(unittest.TestCase):
    def test_wide_glyph_once(self):
        cv = Canvas(6, 1)
        cv.put(0, 0, "日a")
        line = plain_lines(cv)[0]
        self.assertEqual(line, "日a   ")
        self.assertEqual(line.count("日"), 1)

    def test_no_ansi(self):
        cv = Canvas(4, 2)
        cv.put(0, 0, "hi", "\x1b[1m")
        lines = plain_lines(cv)
        self.assertEqual(lines, ["hi  ", "    "])
        self.assertNotIn("\x1b", "".join(lines))

    def test_render_plain_joins(self):
        cv = Canvas(2, 2)
        cv.put(0, 0, "ab")
        cv.put(1, 0, "cd")
        self.assertEqual(render_plain(cv), "ab\ncd")

    def test_styled_lines_alias(self):
        cv = Canvas(3, 2)
        self.assertEqual(styled_lines(cv), cv.to_lines())


class TestMaskText(unittest.TestCase):
    def test_clock_regex(self):
        s = "kickoff 12:34:56 local"
        out = mask_text(s, [(r"\d\d:\d\d:\d\d", "HH:MM:SS")])
        self.assertEqual(out, "kickoff HH:MM:SS local")

    def test_compiled_pattern(self):
        pat = re.compile(r"\d+'")
        out = mask_text("goal 87' late", [(pat, "MM'")])
        self.assertEqual(out, "goal MM' late")


class TestFramesEqual(unittest.TestCase):
    def test_str_vs_list(self):
        self.assertTrue(frames_equal("ab\ncd", ["ab", "cd"]))
        self.assertTrue(frames_equal(["ab", "cd"], ["ab", "cd"]))
        self.assertFalse(frames_equal("ab\ncd", ["ab", "ce"]))

    def test_masks_applied_to_both(self):
        masks = [(r"\d\d:\d\d", "T")]
        self.assertTrue(frames_equal("at 09:15", ["at 21:40"], masks))
        self.assertFalse(frames_equal("at 09:15", "by 09:15", masks))


class TestFirstDiff(unittest.TestCase):
    def test_position(self):
        d = first_diff(["ab", "cd", "ef"], ["ab", "cX", "ef"])
        self.assertEqual(d, (1, "cd", "cX"))

    def test_equal_returns_none(self):
        self.assertIsNone(first_diff("ab\ncd", ["ab", "cd"]))

    def test_masked_equal(self):
        masks = [(r"\d+", "N")]
        self.assertIsNone(first_diff(["t 12"], ["t 99"], masks))

    def test_unequal_lengths(self):
        d = first_diff(["ab"], ["ab", "cd"])
        self.assertEqual(d, (1, "", "cd"))
        d = first_diff(["ab", "cd"], ["ab"])
        self.assertEqual(d, (1, "cd", ""))


if __name__ == "__main__":
    unittest.main()
