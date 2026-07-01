"""Canvas cell-grid behavior."""

import unittest

from tui.canvas import Canvas, LIGHT
from tui.term import RESET


class TestPut(unittest.TestCase):
    def test_basic_write(self):
        cv = Canvas(10, 2)
        end = cv.put(0, 0, "hi")
        self.assertEqual(end, 2)
        self.assertEqual(cv.grid[0][0].ch, "h")
        self.assertEqual(cv.grid[0][1].ch, "i")

    def test_wide_glyph_continuation(self):
        cv = Canvas(10, 1)
        end = cv.put(0, 0, "日a")
        self.assertEqual(end, 3)
        self.assertEqual(cv.grid[0][0].ch, "日")
        self.assertTrue(cv.grid[0][1].cont)
        self.assertEqual(cv.grid[0][2].ch, "a")

    def test_clips_at_edges(self):
        cv = Canvas(3, 1)
        cv.put(0, 1, "abcdef")
        self.assertEqual(cv.grid[0][1].ch, "a")
        self.assertEqual(cv.grid[0][2].ch, "b")
        # negative / out-of-range rows are no-ops
        self.assertEqual(cv.put(-1, 0, "x"), 0)
        self.assertEqual(cv.put(5, 0, "x"), 0)

    def test_newline_stops(self):
        cv = Canvas(10, 1)
        cv.put(0, 0, "a\nb")
        self.assertEqual(cv.grid[0][1].ch, " ")


class TestPutClipped(unittest.TestCase):
    def test_truncates_to_maxw(self):
        cv = Canvas(20, 1)
        cv.put_clipped(0, 0, "abcdefgh", maxw=4)
        row = "".join(c.ch for c in cv.grid[0]).rstrip()
        self.assertEqual(row, "abc…")


class TestBox(unittest.TestCase):
    def test_corners_and_title(self):
        cv = Canvas(10, 4)
        cv.box(0, 0, 4, 10, chars=LIGHT, title="T")
        self.assertEqual(cv.grid[0][0].ch, LIGHT["tl"])
        self.assertEqual(cv.grid[0][9].ch, LIGHT["tr"])
        self.assertEqual(cv.grid[3][0].ch, LIGHT["bl"])
        self.assertEqual(cv.grid[3][9].ch, LIGHT["br"])
        # title " T " lands at column 2
        self.assertEqual(cv.grid[0][3].ch, "T")

    def test_degenerate_no_crash(self):
        cv = Canvas(10, 4)
        cv.box(0, 0, 1, 10)  # h < 2: silently skipped
        self.assertEqual(cv.grid[0][0].ch, " ")


class TestToLines(unittest.TestCase):
    def test_style_runs_coalesced(self):
        cv = Canvas(4, 1)
        cv.put(0, 0, "ab", "S1")
        cv.put(0, 2, "cd", "S2")
        line = cv.to_lines()[0]
        # one style switch per run, not per cell
        self.assertEqual(line.count("S1"), 1)
        self.assertEqual(line.count("S2"), 1)
        self.assertTrue(line.endswith(RESET))

    def test_row_count(self):
        cv = Canvas(3, 5)
        self.assertEqual(len(cv.to_lines()), 5)


class TestBlit(unittest.TestCase):
    def test_copies_content(self):
        a = Canvas(6, 3)
        b = Canvas(2, 1)
        b.put(0, 0, "xy")
        a.blit(b, 1, 2)
        self.assertEqual(a.grid[1][2].ch, "x")
        self.assertEqual(a.grid[1][3].ch, "y")

    def test_clips_out_of_bounds(self):
        a = Canvas(3, 2)
        b = Canvas(5, 5)
        b.put(0, 0, "zzzzz")
        a.blit(b, -1, -1)  # must not raise
        a.blit(b, 1, 2)
        self.assertEqual(a.grid[1][2].ch, "z")


class TestFillRect(unittest.TestCase):
    def test_fill_and_clip(self):
        cv = Canvas(4, 2)
        cv.fill_rect(0, 2, 5, 5, "S", ch="#")
        self.assertEqual(cv.grid[0][2].ch, "#")
        self.assertEqual(cv.grid[1][3].ch, "#")
        self.assertEqual(cv.grid[0][0].ch, " ")


if __name__ == "__main__":
    unittest.main()
