"""Canvas cell-grid behavior."""

import unittest

from tui.canvas import Canvas, HEAVY, LIGHT
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


class TestBlitClipEdgeTears(unittest.TestCase):
    """Regression: wide-glyph tear repair at DESTINATION clip edges
    (review finding: blit previously repaired only source-window edges)."""

    def _row_width(self, cv, r=0):
        import re
        from tui import term
        line = re.sub(r"\x1b\[[0-9;]*m", "", cv.to_lines()[r])
        return sum(term.char_width(ch) for ch in line)

    def test_right_clip_edge_drops_glyph(self):
        # clip x1=3 interior; wide lead would land at col 2 with cont clipped
        src = Canvas(6, 1)
        src.put(0, 0, "ａｂｃ")
        dst = Canvas(10, 1)
        dst.region(0, 0, 1, 3).region(0, 0, 1, 6).blit(src)
        self.assertEqual(self._row_width(dst), 10)   # was 11 pre-fix
        self.assertEqual(dst.grid[0][2].ch, " ")     # repaired, not torn

    def test_left_clip_edge_orphan_cont(self):
        # window starts left of the clip: cont cell lands at x0 leadless
        src = Canvas(6, 1)
        src.put(0, 0, "ａｂｃ")
        dst = Canvas(10, 1)
        # region cols [1,6); blit window from src col 0: lead at dest 0 is
        # clipped, its cont would land at dest col 1 (x0) as an orphan
        dst.region(0, 1, 1, 5).blit(src, c=-1)
        self.assertEqual(self._row_width(dst), 10)   # was 9 pre-fix
        self.assertFalse(dst.grid[0][1].cont)

    def test_source_legacy_edge_lead_repaired(self):
        # source's last column holds a legacy lead-only wide glyph; copying
        # it into an interior dest column must repair it to a space
        src = Canvas(3, 1)
        src.put(0, 2, "ａ")            # lead-only at src canvas edge
        dst = Canvas(10, 1)
        dst.blit(src, 0, 0)
        self.assertEqual(dst.grid[0][2].ch, " ")
        self.assertEqual(self._row_width(dst), 10)

    def test_dest_canvas_edge_keeps_legacy_lead(self):
        # at the destination CANVAS edge the legacy lead-only write is kept,
        # byte-matching Canvas.put's behavior there
        src = Canvas(2, 1)
        src.put(0, 0, "ａ")
        dst = Canvas(3, 1)
        dst.blit(src, 0, 2)            # lead lands in dst's last column
        self.assertEqual(dst.grid[0][2].ch, "ａ")


class TestClear(unittest.TestCase):
    """clear(): the in-place frame reset must leave the canvas
    indistinguishable from a freshly allocated one."""

    W, H = 10, 4

    def _dirty(self, cv):
        """An arbitrary prior frame: styles, boxes, wide glyphs, and a
        torn edge (lead-only wide glyph in the last column)."""
        cv.fill_rect(0, 0, self.H, self.W, "D0", ch="#")
        cv.box(0, 0, 4, 8, "D1", chars=HEAVY, title="old", fill_style="D2")
        cv.put(1, 1, "日本語", "D3")
        cv.put(2, self.W - 1, "日", "D4")   # legacy lead-only at canvas edge
        cv.hline(3, 0, self.W, "D5", "=")

    def _compose_boxes(self, cv):
        cv.box(0, 0, 4, 10, "B", chars=LIGHT, title="T", fill_style="F")
        cv.box(1, 5, 3, 5, "S", chars=HEAVY)

    def _compose_wide(self, cv):
        cv.put(0, 0, "日本語", "W")
        cv.put(1, 8, "日", "W")                    # torn edge: lead-only
        cv.put(2, 0, "ab日", "W", clip=(0, 0, 3, 3))  # straddler dropped
        cv.put(3, 1, "x日y", "S")

    def _compose_styled(self, cv):
        cv.put(0, 0, "ab", "S1")
        cv.put(0, 2, "cd", "S2")
        cv.fill_rect(1, 1, 2, 4, "S3", ch="@")
        cv.hline(3, 0, 9, "S4", "-")
        cv.vline(0, 9, 4, "S5", "|")

    def assert_equiv(self, compose):
        fresh = Canvas(self.W, self.H)
        used = Canvas(self.W, self.H)
        self._dirty(used)
        used.clear()
        compose(fresh)
        compose(used)
        self.assertEqual(fresh.to_lines(), used.to_lines())

    def test_boxes_equivalent_to_fresh(self):
        self.assert_equiv(self._compose_boxes)

    def test_wide_glyphs_equivalent_to_fresh(self):
        self.assert_equiv(self._compose_wide)

    def test_styled_runs_equivalent_to_fresh(self):
        self.assert_equiv(self._compose_styled)

    def test_cont_flags_and_chars_reset(self):
        cv = Canvas(4, 1, "BG")
        cv.put(0, 0, "日日", "S")
        cv.clear()
        for c in cv.grid[0]:
            self.assertEqual(c.ch, " ")
            self.assertEqual(c.style, "BG")
            self.assertFalse(c.cont)

    def test_clear_matches_blank_fresh_canvas(self):
        used = Canvas(6, 3, "BG")
        self._compose_styled(used)
        used.clear()
        self.assertEqual(used.to_lines(), Canvas(6, 3, "BG").to_lines())

    def test_clear_with_bg_updates_default(self):
        cv = Canvas(6, 3, "OLD")
        cv.put(0, 0, "x", "S")
        cv.clear("NEW")
        self.assertEqual(cv.bg, "NEW")
        self.assertEqual(cv.to_lines(), Canvas(6, 3, "NEW").to_lines())
        # the new default persists across a later bare clear()
        cv.put(1, 1, "y", "S")
        cv.clear()
        self.assertEqual(cv.to_lines(), Canvas(6, 3, "NEW").to_lines())

    def test_clear_without_bg_keeps_default(self):
        cv = Canvas(6, 3, "BG")
        cv.clear()
        self.assertEqual(cv.bg, "BG")

    def test_no_reallocation(self):
        cv = Canvas(self.W, self.H)
        self._dirty(cv)
        before = [id(c) for row in cv.grid for c in row]
        cv.clear("NEW")
        after = [id(c) for row in cv.grid for c in row]
        self.assertEqual(before, after)
