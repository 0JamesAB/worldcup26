"""Region: local-coordinate, clipped drawing over a Canvas."""

import unittest

from tui import term, widgets
from tui.canvas import Canvas, LIGHT
from tui.interact import HitMap
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
        cv.region().put_clipped(0, 0, "abcdefgh", maxw=4)
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
                x = rg.center(msg, "S", row=1)
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
        end = rg.left("abc", "S", row=1, pad=1)
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
        rg.left("b", self.st, row=1)
        rg.right("c", self.st, row=2)
        rg.center("d", self.st, row=3)
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
               fillstyle=self.st)
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
            rg.center("mid", style, row=1)
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


if __name__ == "__main__":
    unittest.main()
