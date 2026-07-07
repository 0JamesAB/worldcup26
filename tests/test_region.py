"""Region: local-coordinate, clipped drawing over a Canvas."""

import unittest

from tui import term, widgets
from tui.canvas import Canvas, HEAVY, LIGHT
from tui.interact import HitMap, ListState, ScrollState
from tui.layout import Flex, Rect, hsplit, vsplit
from tui.region import Region
from tui.styles import Style


def row_text(cv, y):
    return "".join(c.ch if c.ch else " " for c in cv.grid[y])


def hit_cells(hits, h, w):
    """Every (row, col) where the HitMap answers something."""
    return {(y, x) for y in range(h) for x in range(w)
            if hits.lookup(y, x) is not None}


class TestConstruction(unittest.TestCase):
    def test_canvas_factory(self):
        cv = Canvas(10, 4)
        rg = cv.region(1, 2, 2, 5)
        self.assertIsInstance(rg, Region)
        self.assertEqual(rg.rect, Rect(1, 2, 2, 5))

    def test_none_sizes_run_to_edge(self):
        cv = Canvas(10, 4)
        rg = cv.region(1, 2)
        self.assertEqual(rg.rect, Rect(1, 2, 3, 8))

    def test_nested_origin_is_absolute(self):
        cv = Canvas(20, 10)
        a = cv.region(2, 3, 6, 12)
        b = a.sub(1, 2, 3, 4)
        self.assertEqual(b.rect, Rect(3, 5, 3, 4))

    def test_nested_none_sizes_run_to_parent_edge(self):
        cv = Canvas(20, 10)
        a = cv.region(2, 3, 6, 12)
        b = a.sub(1, 2)
        self.assertEqual(b.rect, Rect(3, 5, 5, 10))

    def test_hits_and_style_inherit_from_region_parent(self):
        hits = HitMap()
        cv = Canvas(10, 4)
        root = cv.region(hits=hits, style="BG")
        child = root.sub(1, 1, 2, 2)
        self.assertIs(child.hits, hits)
        self.assertEqual(child.style, "BG")

    def test_child_overrides_hits_and_style(self):
        hits, mine = HitMap(), HitMap()
        cv = Canvas(10, 4)
        root = cv.region(hits=hits, style="BG")
        child = root.sub(0, 0, 2, 2, hits=mine, style="S2")
        self.assertIs(child.hits, mine)
        self.assertEqual(child.style, "S2")

    def test_canvas_parent_defaults(self):
        cv = Canvas(10, 4)
        rg = cv.region()
        self.assertIsNone(rg.hits)
        self.assertEqual(rg.style, "")

    def test_negative_sizes_clamp_to_zero(self):
        cv = Canvas(10, 4)
        rg = cv.region(0, 0, -3, -1)
        self.assertEqual((rg.h, rg.w), (0, 0))


class TestPutTranslation(unittest.TestCase):
    def test_local_coords_and_end_col(self):
        cv = Canvas(10, 4)
        rg = cv.region(1, 2, 2, 5)
        end = rg.put(0, 1, "hi")
        self.assertEqual(end, 3)  # local
        self.assertEqual(cv.grid[1][3].ch, "h")
        self.assertEqual(cv.grid[1][4].ch, "i")

    def test_clips_at_region_right_edge(self):
        cv = Canvas(10, 2)
        rg = cv.region(0, 1, 1, 4)
        rg.put(0, 0, "abcdef")
        self.assertEqual(row_text(cv, 0), " abcd     ")

    def test_row_outside_region_is_noop(self):
        cv = Canvas(10, 4)
        rg = cv.region(1, 1, 2, 5)
        self.assertEqual(rg.put(-1, 0, "x"), 0)
        self.assertEqual(rg.put(5, 0, "x"), 0)
        self.assertEqual(row_text(cv, 0), " " * 10)

    def test_max_w_matches_hand_idiom(self):
        txt = "abcdefghij"
        a = Canvas(20, 1)
        a.put(0, 2, term.strip_ansi(term.truncate(txt, 6, ellipsis="…")), "S")
        b = Canvas(20, 1)
        b.region().put(0, 2, txt, "S", max_w=6)
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_max_w_no_truncation_when_it_fits(self):
        cv = Canvas(10, 1)
        cv.region().put(0, 0, "abc", max_w=5)
        self.assertEqual(row_text(cv, 0).rstrip(), "abc")

    def test_put_clipped_alias(self):
        cv = Canvas(10, 1)
        cv.region().put_clipped(0, 0, "abcdefgh", max_w=4)
        self.assertEqual(row_text(cv, 0).rstrip(), "abc…")


class TestWideGlyphs(unittest.TestCase):
    def test_interior_edge_drops_whole_glyph(self):
        cv = Canvas(10, 1)
        rg = cv.region(0, 0, 1, 3)
        end = rg.put(0, 0, "ab日")
        self.assertEqual(cv.grid[0][1].ch, "b")
        self.assertEqual(cv.grid[0][2].ch, " ")
        self.assertFalse(cv.grid[0][3].cont)
        self.assertEqual(end, 2)

    def test_canvas_edge_keeps_legacy_lead_only_write(self):
        cv = Canvas(3, 1)
        cv.region().put(0, 0, "ab日")
        self.assertEqual(cv.grid[0][2].ch, "日")

    def test_region_output_matches_bare_canvas_at_edge(self):
        a = Canvas(3, 1)
        a.put(0, 0, "ab日", "S")
        b = Canvas(3, 1)
        b.region().put(0, 0, "ab日", "S")
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_wide_end_col_is_local(self):
        cv = Canvas(10, 1)
        rg = cv.region(0, 2, 1, 8)
        self.assertEqual(rg.put(0, 0, "日a"), 3)


class TestNestedClip(unittest.TestCase):
    def test_child_clipped_to_parent(self):
        cv = Canvas(12, 6)
        outer = cv.region(1, 1, 4, 8)      # abs rows 1..5, cols 1..9
        inner = outer.sub(1, 2, 10, 10)    # overflows: clip rows 2..5, cols 3..9
        inner.put(0, 0, "abcdefghij")
        self.assertEqual(row_text(cv, 2), "   abcdef   ")

    def test_three_levels_deep(self):
        cv = Canvas(12, 6)
        a = cv.region(0, 0, 6, 12)
        b = a.sub(1, 1, 4, 6)              # abs cols 1..7
        c = b.sub(0, 2, 10, 10)            # abs cols 3..; clip cols 3..7
        c.put(1, 0, "zzzzzzzz")
        self.assertEqual(row_text(cv, 2), "   zzzz     ")

    def test_fill_confined_to_region(self):
        cv = Canvas(6, 4)
        cv.region(1, 2, 2, 3).fill("S")
        for y in range(4):
            for x in range(6):
                inside = 1 <= y < 3 and 2 <= x < 5
                self.assertEqual(cv.grid[y][x].style, "S" if inside else "")

    def test_fill_rect_clipped_by_region(self):
        cv = Canvas(8, 4)
        rg = cv.region(1, 1, 2, 4)
        rg.fill_rect(-1, -1, 10, 10, "S", ch="#")
        self.assertEqual(row_text(cv, 0), " " * 8)
        self.assertEqual(row_text(cv, 1), " ####   ")
        self.assertEqual(row_text(cv, 2), " ####   ")
        self.assertEqual(row_text(cv, 3), " " * 8)

    def test_region_partially_off_canvas(self):
        cv = Canvas(5, 3)
        rg = cv.region(1, 3, 5, 5)  # sticks out right and bottom
        rg.fill("S")
        self.assertEqual(row_text(cv, 1), "   " + "  ")
        self.assertEqual(cv.grid[1][3].style, "S")
        self.assertEqual(cv.grid[2][4].style, "S")
        self.assertEqual(cv.grid[0][3].style, "")


class TestEmptyRegions(unittest.TestCase):
    def _assert_all_noop(self, rg, cv):
        rg.put(0, 0, "x", "S")
        rg.put(0, 0, "x", "S", max_w=3)
        rg.fill("S")
        rg.fill_rect(0, 0, 3, 3, "S", ch="#")
        rg.hline(0, 0)
        rg.vline(0, 0)
        rg.box()
        rg.left("x")
        rg.right("x")
        rg.center("x")
        rg.at(0).write("x").ln().write("y")
        src = Canvas(3, 3)
        src.put(0, 0, "abc")
        rg.blit(src)
        for y in range(cv.h):
            self.assertEqual(row_text(cv, y), " " * cv.w)
            for x in range(cv.w):
                self.assertEqual(cv.grid[y][x].style, "")

    def test_zero_size_region(self):
        cv = Canvas(6, 4)
        self._assert_all_noop(cv.region(2, 2, 0, 0), cv)

    def test_region_fully_off_canvas(self):
        cv = Canvas(6, 4)
        self._assert_all_noop(cv.region(10, 10, 3, 3), cv)

    def test_child_fully_off_parent(self):
        cv = Canvas(8, 6)
        parent = cv.region(1, 1, 2, 3)
        self._assert_all_noop(parent.sub(5, 5, 2, 2), cv)

    def test_empty_region_registers_no_hits(self):
        hits = HitMap()
        cv = Canvas(6, 4)
        cv.region(2, 2, 0, 5, hits=hits).hit("a")
        cv.region(10, 0, 2, 2, hits=hits).hit("b")
        self.assertEqual(len(hits), 0)


class TestFillAndLines(unittest.TestCase):
    def test_fill_defaults_to_region_style(self):
        cv = Canvas(6, 3)
        rg = cv.region(0, 0, 2, 3, style="BG")
        rg.fill()
        self.assertEqual(cv.grid[0][0].style, "BG")
        self.assertEqual(cv.grid[1][2].style, "BG")

    def test_fill_explicit_style_wins(self):
        cv = Canvas(6, 3)
        rg = cv.region(0, 0, 2, 3, style="BG")
        rg.fill("S2")
        self.assertEqual(cv.grid[0][0].style, "S2")

    def test_region_style_never_merged_into_text(self):
        # the de-coalescing trap: put must not compose region.style in
        cv = Canvas(6, 2)
        rg = cv.region(0, 0, 2, 6, style="BG")
        rg.put(0, 0, "x", "FG")
        rg.put(0, 1, "y")
        self.assertEqual(cv.grid[0][0].style, "FG")
        self.assertEqual(cv.grid[0][1].style, "")

    def test_hline_to_edge(self):
        cv = Canvas(8, 3)
        rg = cv.region(1, 1, 2, 5)
        rg.hline(0, 2)
        self.assertEqual(row_text(cv, 1), "   ───  ")

    def test_hline_explicit_length_clipped(self):
        cv = Canvas(8, 3)
        rg = cv.region(1, 1, 2, 5)
        rg.hline(1, 0, 99, ch="=")
        self.assertEqual(row_text(cv, 2), " =====  ")

    def test_vline_to_edge(self):
        cv = Canvas(6, 5)
        rg = cv.region(1, 2, 3, 2)
        rg.vline(1, 0)
        col = "".join(cv.grid[y][2].ch for y in range(5))
        self.assertEqual(col, "  ││ ")


class TestBox(unittest.TestCase):
    def test_returns_inner_region(self):
        cv = Canvas(12, 6)
        rg = cv.region(1, 1, 5, 10)
        inner = rg.box()
        self.assertEqual(inner.rect, Rect(2, 2, 3, 8))
        inner.put(0, 0, "x")
        self.assertEqual(cv.grid[2][2].ch, "x")

    def test_border_translated(self):
        cv = Canvas(12, 6)
        cv.region(1, 1, 5, 10).box()
        self.assertEqual(cv.grid[1][1].ch, LIGHT["tl"])
        self.assertEqual(cv.grid[1][10].ch, LIGHT["tr"])
        self.assertEqual(cv.grid[5][1].ch, LIGHT["bl"])
        self.assertEqual(cv.grid[5][10].ch, LIGHT["br"])

    def test_box_clipped_by_parent(self):
        cv = Canvas(12, 6)
        rg = cv.region(0, 0, 3, 12)
        rg.box(0, 0, 6, 12)  # taller than the region: bottom edge clipped
        self.assertEqual(cv.grid[0][0].ch, LIGHT["tl"])
        self.assertEqual(cv.grid[2][0].ch, LIGHT["v"])
        self.assertEqual(row_text(cv, 5), " " * 12)

    def test_degenerate_inner_region_is_empty(self):
        cv = Canvas(10, 4)
        inner = cv.region(0, 0, 1, 10).box()
        self.assertEqual((inner.h, inner.w), (0, 8))


class TestRowsColsInset(unittest.TestCase):
    def test_rows_cols_match_python_slices(self):
        cv = Canvas(11, 7)
        rg = cv.region(1, 2, 5, 8)
        cases = [(0, None), (2, None), (2, -1), (-2, None), (-4, -1),
                 (1, 3), (3, 99), (-99, 2), (4, 2), (0, 0)]
        for a, b in cases:
            sl = list(range(rg.h))[a:b]
            sub = rg.rows(a, b)
            self.assertEqual(sub.h, len(sl), (a, b))
            self.assertEqual(sub.w, rg.w, (a, b))
            if sl:
                self.assertEqual(sub.rect.r, rg.rect.r + sl[0], (a, b))
            sl = list(range(rg.w))[a:b]
            sub = rg.cols(a, b)
            self.assertEqual(sub.w, len(sl), (a, b))
            self.assertEqual(sub.h, rg.h, (a, b))
            if sl:
                self.assertEqual(sub.rect.c, rg.rect.c + sl[0], (a, b))

    def test_rows_negative_slice_draws_at_bottom(self):
        cv = Canvas(6, 5)
        cv.region().rows(-2).put(0, 0, "x")
        self.assertEqual(cv.grid[3][0].ch, "x")

    def test_inset_matches_rect_inset(self):
        cv = Canvas(20, 10)
        rg = cv.region(1, 2, 8, 16)
        self.assertEqual(rg.inset(1, 2).rect, rg.rect.inset(1, 2))
        self.assertEqual(rg.inset(2).rect, rg.rect.inset(2))
        self.assertEqual(rg.inset(0, 2).rect, rg.rect.inset(0, 2))

    def test_inset_clamps(self):
        cv = Canvas(6, 4)
        rg = cv.region(0, 0, 4, 6).inset(3, 4)
        self.assertEqual((rg.h, rg.w), (0, 0))


class TestSplit(unittest.TestCase):
    def test_split_h_matches_layout_hsplit(self):
        cv = Canvas(30, 12)
        rg = cv.region(1, 2, 8, 26)
        parts = rg.split_h(4, Flex(), Flex(weight=2), 6, gap=1)
        rects = hsplit(Rect(0, 0, 8, 26), 4, Flex(), Flex(weight=2), 6, gap=1)
        self.assertEqual(len(parts), len(rects))
        for part, rc in zip(parts, rects):
            self.assertEqual(part.rect, Rect(rc.r + 1, rc.c + 2, rc.h, rc.w))

    def test_split_v_matches_layout_vsplit(self):
        cv = Canvas(30, 12)
        rg = cv.region(2, 1, 9, 20)
        parts = rg.split_v(1, Flex(min=3), 2, gap=1)
        rects = vsplit(Rect(0, 0, 9, 20), 1, Flex(min=3), 2, gap=1)
        for part, rc in zip(parts, rects):
            self.assertEqual(part.rect, Rect(rc.r + 2, rc.c + 1, rc.h, rc.w))

    def test_split_children_inherit_hits_and_style(self):
        hits = HitMap()
        cv = Canvas(20, 6)
        rg = cv.region(hits=hits, style="BG")
        for part in rg.split_h(5, Flex()):
            self.assertIs(part.hits, hits)
            self.assertEqual(part.style, "BG")


class TestHit(unittest.TestCase):
    def test_whole_region_hit(self):
        hits = HitMap()
        cv = Canvas(10, 6)
        cv.region(1, 2, 2, 3, hits=hits).hit("go")
        expect = {(y, x) for y in (1, 2) for x in (2, 3, 4)}
        self.assertEqual(hit_cells(hits, 6, 10), expect)
        self.assertEqual(hits.lookup(1, 2), "go")

    def test_sub_rect_hit(self):
        hits = HitMap()
        cv = Canvas(10, 6)
        cv.region(1, 1, 4, 8, hits=hits).hit("a", r=1, c=2, h=1, w=3)
        expect = {(2, x) for x in (3, 4, 5)}
        self.assertEqual(hit_cells(hits, 6, 10), expect)

    def test_partially_off_parent_registers_visible_slice(self):
        hits = HitMap()
        cv = Canvas(10, 6)
        parent = cv.region(1, 1, 4, 6, hits=hits)   # abs rows 1..5, cols 1..7
        child = parent.sub(2, 4, 5, 8)              # visible: rows 3..5, cols 5..7
        child.hit("go")
        self.assertEqual(len(hits), 1)
        expect = {(y, x) for y in (3, 4) for x in (5, 6)}
        self.assertEqual(hit_cells(hits, 6, 10), expect)

    def test_hit_rect_clipped_not_just_region(self):
        hits = HitMap()
        cv = Canvas(10, 6)
        rg = cv.region(1, 1, 3, 4, hits=hits)
        rg.hit("x", r=2, c=2, h=5, w=9)  # overflows the region itself
        expect = {(3, 3), (3, 4)}
        self.assertEqual(hit_cells(hits, 6, 10), expect)

    def test_no_hitmap_is_noop(self):
        cv = Canvas(10, 6)
        cv.region().hit("go")  # must not raise

    def test_inherited_through_geometry(self):
        hits = HitMap()
        cv = Canvas(10, 6)
        root = cv.region(hits=hits)
        root.rows(1, 3).cols(2, 5).hit("deep")
        self.assertEqual(hits.lookup(1, 2), "deep")
        self.assertEqual(hits.lookup(2, 4), "deep")
        self.assertIsNone(hits.lookup(3, 2))
        self.assertIsNone(hits.lookup(1, 5))


class TestBlit(unittest.TestCase):
    def _src(self):
        src = Canvas(20, 10)
        src.put(3, 4, "XYZ")
        return src

    def test_viewport_window(self):
        cv = Canvas(10, 5)
        view = cv.region(1, 1, 3, 5)
        view.blit(self._src(), src_r=2, src_c=3)
        self.assertEqual(row_text(cv, 2), "  XYZ     ")
        self.assertEqual(row_text(cv, 1), " " * 10)

    def test_nothing_beyond_region_edge(self):
        src = self._src()
        src.put(3, 9, "Q")  # just past the 5-wide window starting at col 3
        cv = Canvas(10, 5)
        cv.region(1, 1, 3, 5).blit(src, src_r=2, src_c=3)
        self.assertEqual(cv.grid[2][6].ch, " ")
        src.put(6, 3, "R")  # just past the 3-tall window starting at row 2
        cv.region(1, 1, 3, 5).blit(src, src_r=2, src_c=3)
        self.assertEqual(row_text(cv, 4), " " * 10)

    def test_local_offset_shrinks_window(self):
        cv = Canvas(10, 5)
        view = cv.region(0, 0, 3, 6)
        src = Canvas(8, 8)
        src.put(0, 0, "abcdef")
        view.blit(src, r=1, c=2)
        self.assertEqual(row_text(cv, 1), "  abcd    ")

    def test_clipped_by_parent(self):
        cv = Canvas(10, 5)
        parent = cv.region(0, 0, 2, 4)
        view = parent.sub(0, 0, 3, 6)  # clip is still the parent's 2x4
        src = Canvas(8, 8)
        src.put(0, 0, "abcdef")
        src.put(2, 0, "ghijkl")
        view.blit(src)
        self.assertEqual(row_text(cv, 0), "abcd      ")
        self.assertEqual(row_text(cv, 2), " " * 10)

    def test_wide_glyph_tear_repaired(self):
        src = Canvas(4, 1)
        src.put(0, 0, "日x", "S")
        cv = Canvas(6, 2)
        cv.region(0, 0, 1, 3).blit(src, src_c=1)
        self.assertEqual(cv.grid[0][0].ch, " ")  # orphan continuation
        self.assertEqual(cv.grid[0][0].style, "S")
        self.assertFalse(cv.grid[0][0].cont)
        self.assertEqual(cv.grid[0][1].ch, "x")


class TestVerbs(unittest.TestCase):
    def test_center_matches_inset_gutter_idiom(self):
        for cols in range(20, 41):
            for tw in range(1, 15):
                msg = "m" * tw
                a = Canvas(cols, 3)
                widgets.center_msg(a, 1, 1, cols, msg, "S")
                b = Canvas(cols, 3)
                rg = b.region().inset(0, 2)
                x = rg.center(msg, "S", r=1)
                self.assertEqual(a.to_lines(), b.to_lines(), (cols, tw))
                self.assertEqual(
                    x + 2, max(2, (cols - term.display_width(msg)) // 2),
                    (cols, tw))

    def test_right_matches_hand_idiom(self):
        for width in range(8, 24):
            for tw in range(1, 7):
                txt = "r" * tw
                a = Canvas(width, 1)
                a.put(0, width - term.display_width(txt) - 1, txt, "S")
                b = Canvas(width, 1)
                x = b.region().right(txt, "S", pad=1)
                self.assertEqual(a.to_lines(), b.to_lines(), (width, tw))
                self.assertEqual(x, width - tw - 1, (width, tw))

    def test_left_returns_end_col(self):
        cv = Canvas(12, 2)
        rg = cv.region(0, 2, 2, 8)
        end = rg.left("abc", "S", r=1, pad=1)
        self.assertEqual(end, 4)
        self.assertEqual(cv.grid[1][3].ch, "a")

    def test_left_fits_with_ellipsis(self):
        cv = Canvas(12, 1)
        cv.region(0, 0, 1, 5).left("abcdefgh")
        self.assertEqual(row_text(cv, 0).rstrip(), "abcd…")

    def test_right_fits_with_ellipsis(self):
        cv = Canvas(12, 1)
        rg = cv.region(0, 0, 1, 5)
        x = rg.right("abcdefgh")
        self.assertEqual(x, 0)
        self.assertEqual(row_text(cv, 0).rstrip(), "abcd…")

    def test_center_fits_with_ellipsis(self):
        cv = Canvas(12, 1)
        cv.region(0, 0, 1, 6).center("abcdefgh")
        self.assertEqual(row_text(cv, 0).rstrip(), "abcde…")

    def test_center_returns_local_start_col(self):
        cv = Canvas(12, 1)
        x = cv.region(0, 1, 1, 10).center("ab")
        self.assertEqual(x, 4)
        self.assertEqual(cv.grid[0][5].ch, "a")

    def test_degenerate_width_noop(self):
        cv = Canvas(6, 1)
        rg = cv.region(0, 0, 1, 2)
        rg.left("x", pad=3)
        rg.right("x", pad=3)
        rg.center("x", pad=3)
        self.assertEqual(row_text(cv, 0), " " * 6)


class TestCursor(unittest.TestCase):
    def test_flow(self):
        cv = Canvas(20, 5)
        rg = cv.region(1, 1, 3, 12)
        out = rg.at(0).write("ab", "S1").gap(1).write("cd", "S2").ln() \
                .write("ef")
        self.assertIs(out, rg)
        self.assertEqual(row_text(cv, 1), " ab cd" + " " * 14)
        self.assertEqual(cv.grid[1][1].style, "S1")
        self.assertEqual(cv.grid[1][4].style, "S2")
        self.assertEqual(row_text(cv, 2), " ef" + " " * 17)

    def test_at_with_column_and_ln_n(self):
        cv = Canvas(10, 5)
        rg = cv.region()
        rg.at(1, 3).write("x").ln(2).write("y")
        self.assertEqual(cv.grid[1][3].ch, "x")
        self.assertEqual(cv.grid[3][0].ch, "y")

    def test_write_max_w(self):
        cv = Canvas(20, 2)
        rg = cv.region()
        rg.at(0).write("abcdefgh", max_w=4).write("!")
        self.assertEqual(row_text(cv, 0).rstrip(), "abc…!")

    def test_write_advances_by_wide_width(self):
        cv = Canvas(10, 1)
        rg = cv.region()
        rg.at(0).write("日").write("x")
        self.assertEqual(cv.grid[0][2].ch, "x")


class TestStyleObjects(unittest.TestCase):
    def setUp(self):
        self.st = Style(fg=(200, 40, 40), bg=(10, 10, 10)).bold()
        self.s = str(self.st)

    def test_put_and_verbs(self):
        cv = Canvas(12, 4)
        rg = cv.region()
        rg.put(0, 0, "a", self.st)
        rg.left("b", self.st, r=1)
        rg.right("c", self.st, r=2)
        rg.center("d", self.st, r=3)
        self.assertEqual(cv.grid[0][0].style, self.s)
        self.assertEqual(cv.grid[1][0].style, self.s)
        self.assertEqual(cv.grid[2][11].style, self.s)
        self.assertEqual(cv.grid[3][5].style, self.s)

    def test_fill_rect_lines_box_write(self):
        cv = Canvas(12, 6)
        rg = cv.region()
        rg.fill_rect(0, 0, 1, 2, self.st)
        rg.hline(1, 0, 3, self.st)
        rg.vline(2, 0, 2, self.st)
        rg.box(2, 2, 3, 6, style=self.st, title="T", title_style=self.st,
               fill_style=self.st)
        rg.at(5, 9).write("w", self.st)
        self.assertEqual(cv.grid[0][0].style, self.s)
        self.assertEqual(cv.grid[1][1].style, self.s)
        self.assertEqual(cv.grid[2][0].style, self.s)
        self.assertEqual(cv.grid[2][2].style, self.s)  # box border
        self.assertEqual(cv.grid[3][3].style, self.s)  # box fill
        self.assertEqual(cv.grid[5][9].style, self.s)

    def test_region_style_object_used_by_fill(self):
        cv = Canvas(6, 2)
        rg = cv.region(style=self.st)
        self.assertEqual(rg.style, self.s)
        rg.fill()
        self.assertEqual(cv.grid[0][0].style, self.s)

    def test_style_and_string_render_identically(self):
        def scene(rg, style):
            rg.fill(style)
            rg.put(0, 0, "hi", style)
            rg.center("mid", style, r=1)
            rg.box(2, 0, 3, 8, style=style)
            rg.hbar(0.5, style, r=5, c=0, w=6)
        a = Canvas(14, 7)
        scene(a.region(0, 1), self.st)
        b = Canvas(14, 7)
        scene(b.region(0, 1), self.s)
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_widget_sugar_accepts_style_objects(self):
        cv = Canvas(30, 8)
        rg = cv.region()
        rg.badge("B", self.st, r=0)
        rg.rule(r=1, style=self.st, title="t", title_style=self.st)
        rg.spark([1, 2, 3], r=2, style=self.st)
        rg.progress(0.5, self.st, r=3, track_style=self.st)
        rg.card(r=4, h=4, w=12, border_style=self.st, title="T",
                title_style=self.st)
        self.assertEqual(cv.grid[0][1].style, self.s)   # badge text
        self.assertEqual(cv.grid[1][0].style, self.s)   # rule
        self.assertEqual(cv.grid[2][0].style, self.s)   # spark
        self.assertEqual(cv.grid[3][0].style, self.s)   # progress fill
        self.assertEqual(cv.grid[4][0].style, self.s)   # card border

    def test_duel_concatenates_normalized_styles(self):
        lst = Style(fg=(1, 2, 3))
        rst = Style(fg=(4, 5, 6))
        trk = Style(bg=(9, 9, 9))
        cv = Canvas(30, 2)
        cv.region().duel("POSS", "55", "45", lst, rst, track_style=trk)
        a = Canvas(30, 2)
        widgets.draw_duel_row(a, 0, 0, 30, "POSS", "55", "45",
                              str(lst), str(rst), track_style=str(trk))
        self.assertEqual(a.to_lines(), cv.to_lines())


class TestWidgetSugar(unittest.TestCase):
    def test_card_matches_free_function_and_returns_inner(self):
        a = Canvas(20, 8)
        widgets.draw_card(a, 1, 1, 6, 18, title="T", border_style="B",
                          selected=True, select_style="S")
        b = Canvas(20, 8)
        inner = b.region(1, 1, 6, 18).card(title="T", border_style="B",
                                           selected=True, select_style="S")
        self.assertEqual(a.to_lines(), b.to_lines())
        self.assertEqual(inner.rect, Rect(2, 3, 4, 14))
        inner.put(0, 0, "x")
        self.assertEqual(b.grid[2][3].ch, "x")

    def test_card_defaults_cover_region(self):
        cv = Canvas(20, 8)
        inner = cv.region(2, 2, 5, 10).card()
        self.assertEqual(inner.rect, Rect(3, 4, 3, 6))
        self.assertEqual(cv.grid[2][2].ch, LIGHT["tl"])
        self.assertEqual(cv.grid[6][11].ch, LIGHT["br"])

    def test_table_matches_free_function(self):
        spec = [("A", 4, "left"), ("B", -1, "left"), ("C", 3, "right")]
        rows = [[("a1", "S"), ("b1", "S"), ("9", "S")],
                [("a2", "S"), None, ("10", "S")]]
        a = Canvas(24, 6)
        na = widgets.draw_table(a, 1, 2, 18, spec, rows, title="T",
                                title_style="TS", rule_style="RS",
                                header_style="HS")
        b = Canvas(24, 6)
        nb = b.region(1, 2, 5, 18).table(spec, rows, title="T",
                                         title_style="TS", rule_style="RS",
                                         header_style="HS")
        self.assertEqual(a.to_lines(), b.to_lines())
        self.assertEqual(na, nb)

    def test_tab_bar_matches_and_extents_are_local(self):
        tabs = [("1", "Live"), ("2", "Groups")]
        a = Canvas(30, 4)
        ea = widgets.tab_bar(a, 2, 3, 24, tabs, 0, hint="q quit")
        b = Canvas(30, 4)
        eb = b.region(2, 3, 1, 24).tab_bar(tabs, 0, hint="q quit")
        self.assertEqual(a.to_lines(), b.to_lines())
        self.assertEqual([(x - 3, w) for x, w in ea], eb)

    def test_rule_to_edge(self):
        a = Canvas(16, 2)
        widgets.draw_rule(a, 0, 2, 14, title="T", style="S")
        b = Canvas(16, 2)
        b.region(0, 2).rule(title="T", style="S")
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_hbar_progress_return_fill_count(self):
        a = Canvas(20, 2)
        fa = widgets.draw_hbar(a, 0, 0, 10, 0.5, "F", track_style="T")
        pa = widgets.draw_progress(a, 1, 0, 12, 0.5, "F", show_pct=True,
                                   pct_style="P")
        b = Canvas(20, 2)
        rg = b.region()
        fb = rg.hbar(0.5, "F", r=0, w=10, track_style="T")
        pb = rg.progress(0.5, "F", r=1, w=12, show_pct=True, pct_style="P")
        self.assertEqual(a.to_lines(), b.to_lines())
        self.assertEqual((fa, pa), (fb, pb))

    def test_badge_and_spark_return_local_end_col(self):
        cv = Canvas(20, 3)
        rg = cv.region(1, 4)
        self.assertEqual(rg.badge("ok", "S"), 4)   # " ok " from local 0
        self.assertEqual(rg.spark([1, 2, 3], r=1), 3)
        self.assertEqual(cv.grid[1][5].ch, "o")
        self.assertEqual(cv.grid[2][4].ch, "▁")

    def test_gradient_matches_and_returns_local_end(self):
        a = Canvas(20, 1)
        ea = widgets.gradient_put(a, 0, 3, "hot", (255, 0, 0), (0, 0, 255),
                                  extra="X")
        b = Canvas(20, 1)
        eb = b.region(0, 3).gradient("hot", (255, 0, 0), (0, 0, 255),
                                     extra="X")
        self.assertEqual(a.to_lines(), b.to_lines())
        self.assertEqual(ea - 3, eb)

    def test_text_pane_matches_free_function(self):
        lines = ["alpha beta gamma delta", ("hot", "H")]
        a = Canvas(20, 6)
        na = widgets.draw_text_pane(a, 1, 2, 3, 10, lines, ScrollState(),
                                    style="S", pct=True, pct_style="P")
        b = Canvas(20, 6)
        nb = b.region(1, 2, 3, 10).text_pane(lines, ScrollState(), style="S",
                                             pct=True, pct_style="P")
        self.assertEqual(a.to_lines(), b.to_lines())
        self.assertEqual(na, nb)

    def test_text_pane_defaults_cover_region(self):
        a = Canvas(16, 5)
        widgets.draw_text_pane(a, 1, 2, 4, 14, ["one two"], ScrollState(),
                               wrap=False)
        b = Canvas(16, 5)
        b.region(1, 2).text_pane(["one two"], ScrollState(), wrap=False)
        self.assertEqual(a.to_lines(), b.to_lines())

    def test_meter_rows_matches_free_function(self):
        items = [("cpu", 0.42), ("memory", 0.93)]
        a = Canvas(24, 4)
        na = widgets.draw_meter_rows(a, 1, 1, 20, items,
                                     styles=("L", "M", "H"), label_style="B",
                                     track_style="T", show_pct=True,
                                     pct_style="P")
        b = Canvas(24, 4)
        nb = b.region(1, 1, 3, 20).meter_rows(items, styles=("L", "M", "H"),
                                              label_style="B",
                                              track_style="T", show_pct=True,
                                              pct_style="P")
        self.assertEqual(a.to_lines(), b.to_lines())
        self.assertEqual(na, nb)

    def test_sugar_clipped_by_region(self):
        cv = Canvas(10, 4)
        rg = cv.region(1, 1, 2, 4)
        rg.rule(title="verylongtitle")
        rg.badge("wide badge text", "S", r=1)
        for y in range(4):
            for x in range(10):
                inside = 1 <= y < 3 and 1 <= x < 5
                if not inside:
                    self.assertEqual(cv.grid[y][x].ch, " ", (y, x))

    def test_widgets_draw_through_region_as_canvas(self):
        # the free functions accept a Region wherever they take a Canvas
        a = Canvas(20, 4)
        widgets.footer(a, 3, 2, 16, [("q", "quit")], right="r")
        b = Canvas(20, 4)
        widgets.footer(b.region(3, 2, 1, 16), 0, 0, 16, [("q", "quit")],
                       right="r")
        self.assertEqual(a.to_lines(), b.to_lines())


class TestNoEscapes(unittest.TestCase):
    def test_region_exposes_no_grid_or_to_lines(self):
        rg = Canvas(4, 2).region()
        self.assertFalse(hasattr(rg, "grid"))
        self.assertFalse(hasattr(rg, "to_lines"))


def _noop_item(rg, item, i, selected):
    pass


class TestSelectList(unittest.TestCase):
    def _list(self, n_or_heights, sel, h, w=12, hits=None, on_open=None,
              counter=None, draw=None):
        """select_list over n 1-row items (int) or explicit heights (list);
        returns ((start, stop), state, canvas)."""
        if isinstance(n_or_heights, int):
            items = ["item%d" % i for i in range(n_or_heights)]
            item_h = 1
        else:
            items = list(range(len(n_or_heights)))
            item_h = lambda it: n_or_heights[it]
        cv = Canvas(w, h)
        st = ListState(len(items), sel)
        out = cv.region(hits=hits).select_list(
            items, st, draw or _noop_item, item_h=item_h, on_open=on_open,
            counter=counter)
        return out, st, cv

    def test_uniform_degrades_to_bottom_anchored_window(self):
        for sel in range(10):
            out, _, _ = self._list(10, sel, h=4)
            start = max(0, sel - 3)
            self.assertEqual(out, (start, start + 4), sel)

    def test_uniform_all_fit(self):
        out, _, _ = self._list(3, 1, h=6)
        self.assertEqual(out, (0, 3))

    def test_uniform_item_h_int(self):
        # 5 items of 2 rows in 6 rows: three fit; sel at the end anchors
        cv = Canvas(10, 6)
        st = ListState(5, 4)
        out = cv.region().select_list(list("abcde"), st, _noop_item, item_h=2)
        self.assertEqual(out, (2, 5))

    def test_variable_heights_hand_computed(self):
        # the live-card shape: heights 5,5,8,5,5 in a 19-row region
        cases = {0: (0, 3), 1: (0, 3), 2: (0, 3), 3: (1, 4), 4: (2, 5)}
        for sel, want in cases.items():
            out, _, _ = self._list([5, 5, 8, 5, 5], sel, h=19)
            self.assertEqual(out, want, sel)

    def test_whole_items_only_after_the_first(self):
        # heights 3,3: the second is dropped, not clipped, in 5 rows
        out, _, _ = self._list([3, 3], 0, h=5)
        self.assertEqual(out, (0, 1))

    def test_first_windowed_item_always_drawn(self):
        # sel's own item taller than the region still draws (clipped)
        calls = []

        def draw(rg, item, i, selected):
            calls.append((i, selected, rg.h))

        out, _, _ = self._list([3, 10], 1, h=5, draw=draw)
        self.assertEqual(out, (1, 2))
        self.assertEqual(calls, [(1, True, 10)])

    def test_draw_item_regions_and_selection_flag(self):
        rects = []

        def draw(rg, item, i, selected):
            rects.append((i, rg.rect, selected))
            rg.put(0, 0, item)

        cv = Canvas(8, 6)
        st = ListState(3, 1)
        out = cv.region(1, 1, 4, 6).select_list(["aa", "bb", "cc"], st, draw,
                                                item_h=2)
        self.assertEqual(out, (0, 2))
        self.assertEqual(rects, [(0, Rect(1, 1, 2, 6), False),
                                 (1, Rect(3, 1, 2, 6), True)])
        self.assertEqual(row_text(cv, 1)[1:3], "aa")
        self.assertEqual(row_text(cv, 3)[1:3], "bb")

    def test_set_count_syncs_and_clamps_stale_state(self):
        st = ListState(99, 50)
        cv = Canvas(10, 8)
        out = cv.region().select_list(list("abc"), st, _noop_item)
        self.assertEqual((st.count, st.sel), (3, 2))
        self.assertEqual(out, (0, 3))

    def test_empty_items(self):
        called = []
        hits = HitMap()
        out, _, _ = self._list(0, 0, h=4, hits=hits,
                               counter=lambda *a: called.append(a))
        self.assertEqual(out, (0, 0))
        self.assertEqual(called, [])
        self.assertEqual(len(hits), 0)

    def test_click_selects(self):
        hits = HitMap()
        out, st, _ = self._list(6, 1, h=4, hits=hits)
        self.assertEqual(out, (0, 4))
        act = hits.lookup(2, 0)      # row of item 2
        self.assertTrue(callable(act))
        act()
        self.assertEqual(st.sel, 2)

    def test_click_hits_cover_item_rects(self):
        hits = HitMap()
        # heights 2,3 laid out at rows 0..1 and 2..4
        _, st, _ = self._list([2, 3], 1, h=6, hits=hits)
        hits.lookup(1, 11)()          # bottom-right cell of item 0
        self.assertEqual(st.sel, 0)
        hits.lookup(4, 0)()
        self.assertEqual(st.sel, 1)
        self.assertIsNone(hits.lookup(5, 0))   # below the last item

    def test_click_selected_opens(self):
        hits = HitMap()
        opened = []
        _, st, _ = self._list(5, 1, h=5, hits=hits,
                              on_open=lambda item, i: opened.append((item, i)))
        hits.lookup(3, 0)()           # first click: select only
        self.assertEqual(st.sel, 3)
        self.assertEqual(opened, [])
        hits.lookup(3, 0)()           # click the selected item: open
        self.assertEqual(opened, [("item3", 3)])
        self.assertEqual(st.sel, 3)

    def test_click_selected_without_on_open_is_noop(self):
        hits = HitMap()
        _, st, _ = self._list(3, 2, h=4, hits=hits)
        hits.lookup(2, 0)()           # already selected, no on_open
        self.assertEqual(st.sel, 2)

    def test_counter_only_on_overflow(self):
        calls = []
        counter = lambda *a: calls.append(a)
        self._list(4, 0, h=6, counter=counter)     # all fit: not called
        self.assertEqual(calls, [])
        self._list(9, 4, h=3, counter=counter)     # overflow
        self.assertEqual(calls, [(2, 5, 9)])

    def test_no_hitmap_is_fine(self):
        out, _, cv = self._list(4, 0, h=4)         # hits=None: draw only
        self.assertEqual(out, (0, 4))


class TestSelectListMatchesViewLive(unittest.TestCase):
    """A/B oracle: select_list's run-fit windowing reproduces view_live's
    on the live fixture -- same visible cards, same top rows."""

    def test_windowing_matches_view_live(self):
        import os
        import sys
        import time
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from tui import theme as tui_theme
        saved = (term.get_color_depth(), tui_theme.get_theme(),
                 os.environ.get("TZ"), os.environ.get("WCUP_ODDS_FORMAT"))
        try:
            import fixtures_views as F
            import views
            order = {"in": 0, "pre": 1, "post": 2}
            # hand-computed: sorted card heights are 5,5,8,5,5; the card
            # body is rows-5 tall (19 at 80x24, 35 at 120x40: all fit)
            hand = {(80, 24): {0: (0, 3), 1: (0, 3), 2: (0, 3),
                               3: (1, 4), 4: (2, 5)},
                    (120, 40): {s: (0, 5) for s in range(5)}}
            for cols, rows in ((80, 24), (120, 40)):
                for sel in range(5):
                    key = (cols, rows, sel)
                    st = F.state_live()
                    st.live_sel = sel
                    cv = Canvas(cols, rows)
                    # exactly render()'s view_live rect: rows [2, rows-2)
                    views.view_live(cv.region(hits=st.hits).rows(2, -2),
                                    st, F.FRAME + 1)
                    # visible card index -> absolute top row, via its hit:
                    # the actions are select_list click closures, so invoke
                    # one and read the cursor to learn the item's index
                    seen = {}
                    for y in range(rows):
                        for x in range(cols):
                            a = st.hits.lookup(y, x)
                            if a is not None:
                                a()
                                i = st.live_ls.sel
                                seen[i] = min(seen.get(i, y), y)
                    matches = sorted(
                        st.matches_today,
                        key=lambda m: (order.get(m.state, 3), m.date))
                    tops = {}

                    def draw(rg, m, i, s, tops=tops):
                        tops[i] = rg.rect.r

                    body = Canvas(cols, rows).region().rows(3, -2)
                    ls = ListState(len(matches), sel)
                    start, stop = body.select_list(matches, ls, draw,
                                                   item_h=views.card_rows)
                    self.assertEqual((start, stop), hand[(cols, rows)][sel],
                                     key)
                    self.assertEqual(sorted(seen), list(range(start, stop)),
                                     key)
                    for i in range(start, stop):
                        self.assertEqual(tops[i], seen[i], key)
        finally:
            term.set_color_depth(saved[0])
            tui_theme.set_theme(saved[1])
            if saved[2] is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = saved[2]
            time.tzset()
            if saved[3] is None:
                os.environ.pop("WCUP_ODDS_FORMAT", None)
            else:
                os.environ["WCUP_ODDS_FORMAT"] = saved[3]


class TestPopup(unittest.TestCase):
    def test_box_fill_and_inner_region(self):
        cv = Canvas(14, 8)
        rg = cv.region(1, 1, 6, 12, style="BG")
        inner = rg.popup(1, 2, 4, 8, title="T", style="S")
        self.assertEqual(inner.rect, Rect(3, 4, 2, 6))
        self.assertEqual(cv.grid[2][3].ch, LIGHT["tl"])
        self.assertEqual(cv.grid[5][10].ch, LIGHT["br"])
        self.assertEqual(cv.grid[2][3].style, "S")
        # interior fill defaults to region.style
        self.assertEqual(cv.grid[3][4].style, "BG")
        self.assertEqual(row_text(cv, 2)[5:8], " T ")

    def test_fill_style_explicit(self):
        cv = Canvas(10, 5)
        cv.region(style="BG").popup(0, 0, 5, 10, fill_style="F")
        self.assertEqual(cv.grid[1][1].style, "F")

    def test_custom_chars(self):
        cv = Canvas(10, 5)
        cv.region().popup(0, 0, 4, 8, chars=HEAVY)
        self.assertEqual(cv.grid[0][0].ch, HEAVY["tl"])

    def test_swallows_clicks_under_overlay(self):
        hits = HitMap()
        cv = Canvas(12, 8)
        rg = cv.region(hits=hits)
        rg.hit("under")                     # full-screen underlying hit
        rg.popup(2, 2, 4, 8)
        act = hits.lookup(3, 4)             # inside the popup
        self.assertTrue(callable(act))
        self.assertIsNone(act())            # the no-op swallow
        self.assertTrue(callable(hits.lookup(2, 2)))     # border too
        self.assertEqual(hits.lookup(0, 0), "under")     # outside: alive

    def test_content_hits_added_after_win(self):
        hits = HitMap()
        cv = Canvas(12, 8)
        inner = cv.region(hits=hits).popup(1, 1, 5, 10)
        inner.hit("btn", r=0, c=0, h=1, w=4)
        self.assertEqual(hits.lookup(2, 2), "btn")
        self.assertTrue(callable(hits.lookup(3, 2)))

    def test_no_hitmap_registers_nothing(self):
        cv = Canvas(10, 6)
        inner = cv.region().popup(1, 1, 4, 8)   # must not raise
        self.assertEqual((inner.h, inner.w), (2, 6))

    def test_swallow_clipped_to_visible(self):
        hits = HitMap()
        cv = Canvas(10, 6)
        cv.region(hits=hits).popup(4, 4, 6, 10)   # sticks out bottom-right
        self.assertTrue(callable(hits.lookup(5, 9)))
        self.assertIsNone(hits.lookup(3, 4))

    def test_modal_centers(self):
        hits = HitMap()
        cv = Canvas(20, 12)
        inner = cv.region(hits=hits).modal(6, 10, title="M")
        self.assertEqual(inner.rect, Rect(4, 6, 4, 8))
        self.assertTrue(callable(hits.lookup(3, 5)))   # popup border
        self.assertIsNone(hits.lookup(2, 5))           # just outside

    def test_modal_larger_than_region_clamps_origin(self):
        cv = Canvas(10, 6)
        inner = cv.region().modal(10, 14)
        self.assertEqual(inner.rect, Rect(1, 1, 8, 12))


class _Edit:
    """Stand-in for interact.LineEdit: just .text and .cursor."""

    def __init__(self, text="", cursor=None):
        self.text = text
        self.cursor = len(text) if cursor is None else cursor


class TestInput(unittest.TestCase):
    def test_prompt_text_and_cursor_block(self):
        cv = Canvas(20, 1)
        cx = cv.region().input(_Edit("hello"), prompt="> ", style="S")
        self.assertEqual(row_text(cv, 0).rstrip(), "> hello")
        self.assertEqual(cx, 7)
        self.assertEqual(cv.grid[0][2].style, "S")
        self.assertEqual(cv.grid[0][7].ch, " ")
        self.assertEqual(cv.grid[0][7].style, "S" + term.REVERSE)

    def test_cursor_mid_text(self):
        cv = Canvas(20, 1)
        cx = cv.region().input(_Edit("hello", 1), prompt="> ", style="S")
        self.assertEqual(cx, 3)
        self.assertEqual(cv.grid[0][3].ch, "e")
        self.assertEqual(cv.grid[0][3].style, "S" + term.REVERSE)
        self.assertEqual(cv.grid[0][4].style, "S")

    def test_explicit_cursor_style(self):
        cv = Canvas(10, 1)
        cv.region().input(_Edit("a", 0), cursor_style="C")
        self.assertEqual(cv.grid[0][0].style, "C")

    def test_scrolls_to_keep_cursor_at_end_visible(self):
        cv = Canvas(6, 1)
        cx = cv.region().input(_Edit("abcdefghij"))
        self.assertEqual(row_text(cv, 0), "fghij ")
        self.assertEqual(cx, 5)
        self.assertEqual(cv.grid[0][5].style, term.REVERSE)

    def test_scroll_cursor_inside_buffer(self):
        cv = Canvas(6, 1)
        cx = cv.region().input(_Edit("abcdefghij", 7))
        self.assertEqual(row_text(cv, 0), "cdefgh")
        self.assertEqual(cx, 5)
        self.assertEqual(cv.grid[0][5].ch, "h")
        self.assertEqual(cv.grid[0][5].style, term.REVERSE)

    def test_no_scroll_when_it_fits(self):
        cv = Canvas(10, 1)
        cv.region().input(_Edit("abc", 0))
        self.assertEqual(row_text(cv, 0).rstrip(), "abc")
        self.assertEqual(cv.grid[0][0].style, term.REVERSE)

    def test_ghost_suffix_dim_with_cursor_on_first_char(self):
        cv = Canvas(12, 1)
        cx = cv.region().input(_Edit("gr"), style="S", ghost="oups")
        self.assertEqual(row_text(cv, 0).rstrip(), "groups")
        self.assertEqual(cx, 2)
        self.assertEqual(cv.grid[0][2].ch, "o")
        self.assertEqual(cv.grid[0][2].style, "S" + term.REVERSE)
        self.assertEqual(cv.grid[0][3].style, "S" + term.DIM)

    def test_no_ghost_when_text_end_scrolled_off(self):
        cv = Canvas(6, 1)
        cv.region().input(_Edit("abcdefghij", 3), ghost="XY")
        self.assertEqual(row_text(cv, 0), "abcdef")

    def test_ghost_truncated_to_region(self):
        cv = Canvas(8, 1)
        cv.region().input(_Edit("ab"), ghost="cdefghij")
        self.assertEqual(row_text(cv, 0)[:2], "ab")
        self.assertEqual(cv.grid[0][2].ch, "c")   # cursor over ghost[0]

    def test_empty_buffer_cursor_at_origin(self):
        cv = Canvas(6, 1)
        cx = cv.region().input(_Edit(""))
        self.assertEqual(cx, 0)
        self.assertEqual(cv.grid[0][0].style, term.REVERSE)

    def test_prompt_fills_region_no_crash(self):
        cv = Canvas(4, 1)
        cx = cv.region().input(_Edit("abc"), prompt="::::")
        self.assertEqual(cx, 4)

    def test_row_parameter(self):
        cv = Canvas(8, 3)
        cv.region().input(_Edit("x", 0), r=2)
        self.assertEqual(cv.grid[2][0].ch, "x")

    def test_style_objects_normalized(self):
        st = Style(fg=(1, 2, 3))
        cv = Canvas(10, 1)
        cv.region().input(_Edit("a", 1), prompt=">", style=st)
        self.assertEqual(cv.grid[0][0].style, str(st))
        self.assertEqual(cv.grid[0][2].style, str(st) + term.REVERSE)


if __name__ == "__main__":
    unittest.main()


class TestSelectListHitH(unittest.TestCase):
    """Regression: hit_h trims clickable rows (e.g. a trailing gap row
    in an item's layout height must not be clickable)."""

    def test_gap_row_not_clickable(self):
        from tui.canvas import Canvas
        from tui.interact import HitMap, ListState
        cv = Canvas(20, 12)
        hits = HitMap()
        rg = cv.region(hits=hits)
        state = ListState(3)
        opened = []
        rg.select_list(list("abc"), state, lambda irg, it, i, sel: None,
                       item_h=4, hit_h=3,
                       on_open=lambda it, i: opened.append(i))
        # content rows of item 0 are clickable
        self.assertIsNotNone(hits.lookup(2, 5))
        # its gap row (row 3) is not
        self.assertIsNone(hits.lookup(3, 5))
        # second item's content starts at row 4
        act = hits.lookup(4, 5)
        self.assertIsNotNone(act)
        act()                          # click selects item 1
        self.assertEqual(state.sel, 1)
        hits.clear()
        rg.select_list(list("abc"), state, lambda irg, it, i, sel: None,
                       item_h=4, hit_h=3,
                       on_open=lambda it, i: opened.append(i))
        hits.lookup(4, 5)()            # click selected -> opens
        self.assertEqual(opened, [1])


class TestInputWideChars(unittest.TestCase):
    """Regression: input cursor/scroll are display-width aware."""

    def _render(self, text, cursor, w=10, ghost=""):
        from tui.canvas import Canvas
        from tui.interact import LineEdit
        cv = Canvas(w, 1)
        ed = LineEdit()
        ed.buf = text if hasattr(ed, "buf") else None
        # drive through the public API to be safe
        ed.clear()
        for ch in text:
            ed.handle_key(ch)
        while ed.cursor > cursor:
            from tui.term import Key
            ed.handle_key(Key.LEFT)
        rg = cv.region()
        cx = rg.input(ed, ghost=ghost)
        return cv, cx

    def test_cursor_after_wide_glyphs(self):
        cv, cx = self._render("日本語", 3)
        # cursor at end-of-buffer sits at display column 6, not char col 3
        self.assertEqual(cx, 6)
        self.assertEqual(cv.grid[0][0].ch, "日")
        self.assertEqual(cv.grid[0][2].ch, "本")
        self.assertEqual(cv.grid[0][4].ch, "語")

    def test_mid_buffer_cursor_on_wide_glyph(self):
        cv, cx = self._render("日本語", 1)
        self.assertEqual(cx, 2)                    # display col of 本
        self.assertEqual(cv.grid[0][2].ch, "本")   # glyph intact (no tear)
        self.assertFalse(cv.grid[0][3].cont is False and cv.grid[0][3].ch == " "
                         and cv.grid[0][2].ch != "本")

    def test_wide_scroll_keeps_cursor_visible(self):
        # 6 wide glyphs = 12 columns in a 6-column pane; cursor at end
        cv, cx = self._render("абвгде".replace("а", "日")[:1] * 6, 6, w=6)
        self.assertLess(cx, 6)                     # cursor within the pane
        # no torn wide glyph: every lead has its continuation
        row = cv.grid[0]
        for i, cell in enumerate(row):
            if cell.ch and len(cell.ch) == 1 and not cell.cont:
                from tui import term as T
                if T.char_width(cell.ch) == 2 and i + 1 < len(row):
                    self.assertTrue(row[i + 1].cont)
