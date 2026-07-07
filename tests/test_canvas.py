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
        cv.put_clipped(0, 0, "abcdefgh", max_w=4)
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


class TestPutClip(unittest.TestCase):
    def test_none_clip_matches_full_clip(self):
        a = Canvas(6, 2)
        b = Canvas(6, 2)
        a.put(0, 1, "日ab", "S")
        b.put(0, 1, "日ab", "S", clip=(0, 0, 2, 6))
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_interior_wide_glyph_dropped_whole(self):
        cv = Canvas(10, 1)
        cv.put(0, 0, "ab日", clip=(0, 0, 1, 3))
        # the wide glyph would straddle the interior edge at x=3: drop whole
        self.assertEqual(cv.grid[0][1].ch, "b")
        self.assertEqual(cv.grid[0][2].ch, " ")
        self.assertFalse(cv.grid[0][3].cont)
        self.assertEqual(cv.grid[0][3].ch, " ")

    def test_canvas_edge_keeps_legacy_lead_only_write(self):
        # no clip: lead-only write at the last column (0.2.0 behavior)
        a = Canvas(3, 1)
        a.put(0, 0, "ab日")
        self.assertEqual(a.grid[0][2].ch, "日")
        # explicit clip ending at the canvas edge behaves identically
        b = Canvas(3, 1)
        b.put(0, 0, "ab日", clip=(0, 0, 1, 3))
        self.assertEqual(b.grid[0][2].ch, "日")
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_row_and_left_clip(self):
        cv = Canvas(10, 3)
        cv.put(0, 0, "x", clip=(1, 0, 2, 10))  # row outside clip: no-op
        self.assertEqual(cv.grid[0][0].ch, " ")
        cv.put(1, 0, "abcd", clip=(1, 2, 2, 10))
        self.assertEqual(cv.grid[1][1].ch, " ")
        self.assertEqual(cv.grid[1][2].ch, "c")
        self.assertEqual(cv.grid[1][3].ch, "d")

    def test_wide_glyph_straddling_left_clip_edge_skipped(self):
        cv = Canvas(10, 1)
        cv.put(0, 0, "日x", clip=(0, 1, 1, 10))
        self.assertEqual(cv.grid[0][0].ch, " ")
        self.assertEqual(cv.grid[0][1].ch, " ")
        self.assertFalse(cv.grid[0][1].cont)
        self.assertEqual(cv.grid[0][2].ch, "x")

    def test_degenerate_clips_are_noops(self):
        cv = Canvas(5, 2)
        cv.put(0, 0, "abc", clip=(0, 3, 1, 1))
        cv.put(0, 0, "abc", clip=(0, 0, 0, 0))
        cv.fill_rect(0, 0, 2, 5, "S", ch="#", clip=(1, 4, 0, 2))
        cv.hline(0, 0, 5, clip=(0, 0, 0, 5))
        cv.vline(0, 0, 2, clip=(0, 2, 2, 1))
        self.assertEqual("".join(c.ch for c in cv.grid[0]), "     ")
        self.assertEqual("".join(c.ch for c in cv.grid[1]), "     ")


class TestPrimitiveClips(unittest.TestCase):
    def test_put_clipped_threads_clip(self):
        cv = Canvas(10, 1)
        cv.put_clipped(0, 0, "abcdefgh", max_w=6, clip=(0, 0, 1, 4))
        row = "".join(c.ch for c in cv.grid[0]).rstrip()
        self.assertEqual(row, "abcd")

    def test_fill_rect_clip(self):
        cv = Canvas(6, 4)
        cv.fill_rect(0, 0, 4, 6, "S", ch="#", clip=(1, 2, 3, 4))
        for y in range(4):
            for x in range(6):
                want = "#" if 1 <= y < 3 and 2 <= x < 4 else " "
                self.assertEqual(cv.grid[y][x].ch, want)

    def test_fill_rect_unclipped_unchanged(self):
        cv = Canvas(4, 2)
        cv.fill_rect(0, 2, 5, 5, "S", ch="#")
        cv.fill_rect(-1, -1, 2, 2, "S", ch="@")
        self.assertEqual(cv.grid[0][2].ch, "#")
        self.assertEqual(cv.grid[0][0].ch, "@")
        self.assertEqual(cv.grid[1][1].ch, " ")

    def test_hline_vline_clip(self):
        cv = Canvas(8, 4)
        cv.hline(1, 0, 8, ch="-", clip=(0, 2, 4, 5))
        self.assertEqual("".join(c.ch for c in cv.grid[1]), "  ---   ")
        cv.vline(0, 6, 4, ch="|", clip=(1, 0, 3, 8))
        col = "".join(cv.grid[y][6].ch for y in range(4))
        self.assertEqual(col, " || ")

    def test_box_clip(self):
        cv = Canvas(10, 5)
        cv.box(0, 0, 5, 10, clip=(0, 0, 2, 10))
        self.assertEqual(cv.grid[0][0].ch, LIGHT["tl"])
        self.assertEqual(cv.grid[1][0].ch, LIGHT["v"])
        self.assertEqual(cv.grid[4][0].ch, " ")  # bottom edge clipped away
        self.assertEqual(cv.grid[2][0].ch, " ")


class TestHlineFastPath(unittest.TestCase):
    def _old_hline(self, cv, r, c, length, style="", ch="─"):
        for i in range(length):
            cv.put(r, c + i, ch, style)

    def test_narrow_char_byte_equivalent(self):
        a = Canvas(8, 1)
        b = Canvas(8, 1)
        a.hline(0, 1, 5, "S", "─")
        self._old_hline(b, 0, 1, 5, "S", "─")
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_overhanging_narrow_char(self):
        a = Canvas(4, 1)
        b = Canvas(4, 1)
        a.hline(0, 2, 9, "S", "=")
        self._old_hline(b, 0, 2, 9, "S", "=")
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_wide_char_byte_equivalent(self):
        a = Canvas(8, 1)
        b = Canvas(8, 1)
        a.hline(0, 0, 3, "S", "日")
        self._old_hline(b, 0, 0, 3, "S", "日")
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_zero_and_negative_length(self):
        cv = Canvas(4, 1)
        cv.hline(0, 0, 0)
        cv.hline(0, 0, -3)
        self.assertEqual("".join(c.ch for c in cv.grid[0]), "    ")


class TestBlitWindow(unittest.TestCase):
    def test_source_window(self):
        b = Canvas(4, 2)
        b.put(0, 0, "abcd")
        b.put(1, 0, "efgh")
        a = Canvas(6, 3)
        a.blit(b, 0, 0, src_r=1, src_c=1, h=1, w=2)
        self.assertEqual(a.grid[0][0].ch, "f")
        self.assertEqual(a.grid[0][1].ch, "g")
        self.assertEqual(a.grid[0][2].ch, " ")
        self.assertEqual(a.grid[1][0].ch, " ")

    def test_defaults_copy_rest_of_source(self):
        b = Canvas(3, 2)
        b.put(0, 0, "abc")
        b.put(1, 0, "def")
        a = Canvas(4, 3)
        a.blit(b, 0, 0, src_r=1, src_c=1)
        self.assertEqual(a.grid[0][0].ch, "e")
        self.assertEqual(a.grid[0][1].ch, "f")

    def test_orphan_cont_at_window_left_edge_repaired(self):
        b = Canvas(4, 1)
        b.put(0, 0, "日x", "S")
        a = Canvas(4, 1)
        a.blit(b, 0, 0, src_c=1, w=2)
        self.assertEqual(a.grid[0][0].ch, " ")
        self.assertEqual(a.grid[0][0].style, "S")
        self.assertFalse(a.grid[0][0].cont)
        self.assertEqual(a.grid[0][1].ch, "x")

    def test_wide_lead_at_window_right_edge_repaired(self):
        b = Canvas(4, 1)
        b.put(0, 1, "日", "S")
        a = Canvas(4, 1)
        a.blit(b, 0, 0, src_c=0, w=2)
        self.assertEqual(a.grid[0][1].ch, " ")
        self.assertEqual(a.grid[0][1].style, "S")
        self.assertFalse(a.grid[0][1].cont)

    def test_full_blit_keeps_wide_glyph_intact(self):
        b = Canvas(3, 1)
        b.put(0, 0, "日", "S")
        a = Canvas(5, 1)
        a.blit(b, 0, 1)
        self.assertEqual(a.grid[0][1].ch, "日")
        self.assertTrue(a.grid[0][2].cont)

    def test_dest_clip(self):
        b = Canvas(4, 1)
        b.put(0, 0, "abcd")
        a = Canvas(6, 2)
        a.blit(b, 0, 0, clip=(0, 1, 1, 3))
        self.assertEqual("".join(c.ch for c in a.grid[0]), " bc   ")
        self.assertEqual("".join(c.ch for c in a.grid[1]), "      ")

    def test_out_of_range_window_no_crash(self):
        b = Canvas(2, 2)
        b.put(0, 0, "ab")
        a = Canvas(3, 3)
        a.blit(b, 0, 0, src_r=-1, src_c=-1, h=9, w=9)
        # source clamps to (0,0); window origin was (-1,-1) so it lands at (1,1)
        self.assertEqual(a.grid[0][0].ch, " ")
        self.assertEqual(a.grid[1][1].ch, "a")
        a.blit(b, 0, 0, src_r=5, src_c=5)  # empty window: no-op


class TestRegionFactory(unittest.TestCase):
    def test_region_factory(self):
        cv = Canvas(10, 4)
        rg = cv.region(1, 2, 2, 5)
        self.assertEqual(type(rg).__name__, "Region")


if __name__ == "__main__":
    unittest.main()
