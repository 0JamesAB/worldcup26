"""Generalized drawing widgets."""

import unittest

from tui import term
from tui.canvas import Canvas
from tui import widgets


def row_text(cv, r):
    return "".join(c.ch if c.ch else "" for c in cv.grid[r])


class TestCenterMsg(unittest.TestCase):
    def test_centered(self):
        cv = Canvas(20, 5)
        widgets.center_msg(cv, 0, 4, 20, "hi", "S")
        self.assertEqual(row_text(cv, 2).strip(), "hi")
        self.assertEqual(cv.grid[2][9].ch, "h")

    def test_left_clamp(self):
        cv = Canvas(10, 1)
        widgets.center_msg(cv, 0, 0, 10, "a-very-long-message", "S")
        self.assertEqual(cv.grid[0][2].ch, "a")  # clamped to col 2


class TestLerpGradient(unittest.TestCase):
    def test_lerp_endpoints(self):
        self.assertEqual(widgets.lerp_rgb((0, 0, 0), (10, 20, 30), 0), (0, 0, 0))
        self.assertEqual(widgets.lerp_rgb((0, 0, 0), (10, 20, 30), 1), (10, 20, 30))

    def test_gradient_put_colors_and_width(self):
        saved = term.get_color_depth()
        try:
            term.set_color_depth("truecolor")
            cv = Canvas(10, 1)
            end = widgets.gradient_put(cv, 0, 0, "ab", (0, 0, 0), (100, 100, 100))
            self.assertEqual(end, 2)
            self.assertEqual(cv.grid[0][0].style, term.fg(0, 0, 0))
            self.assertEqual(cv.grid[0][1].style, term.fg(100, 100, 100))
        finally:
            term.set_color_depth(saved)

    def test_gradient_put_wide_chars(self):
        cv = Canvas(10, 1)
        end = widgets.gradient_put(cv, 0, 0, "⚽a", (0, 0, 0), (9, 9, 9))
        self.assertEqual(end, 3)  # emoji is 2 cells


class TestDrawHbar(unittest.TestCase):
    def test_fill_and_track(self):
        cv = Canvas(10, 1)
        n = widgets.draw_hbar(cv, 0, 0, 10, 0.5, "F", "T")
        self.assertEqual(n, 5)
        self.assertEqual(row_text(cv, 0), "█████░░░░░")

    def test_no_track(self):
        cv = Canvas(10, 1)
        widgets.draw_hbar(cv, 0, 0, 10, 0.3, "F")
        self.assertEqual(row_text(cv, 0).rstrip(), "███")

    def test_clamps_overflow(self):
        cv = Canvas(10, 1)
        self.assertEqual(widgets.draw_hbar(cv, 0, 0, 10, 1.7, "F"), 10)

    def test_zero(self):
        cv = Canvas(10, 1)
        self.assertEqual(widgets.draw_hbar(cv, 0, 0, 10, 0.0, "F", "T"), 0)
        self.assertEqual(row_text(cv, 0), "░" * 10)


class TestSplitFracs(unittest.TestCase):
    def test_ints(self):
        self.assertEqual(widgets.split_fracs(3, 1), (0.75, 0.25))

    def test_percent_strings(self):
        self.assertEqual(widgets.split_fracs("55%", "45%"), (0.55, 0.45))

    def test_unparseable(self):
        self.assertEqual(widgets.split_fracs("n/a", "n/a"), (0.5, 0.5))

    def test_zero_total(self):
        self.assertEqual(widgets.split_fracs(0, 0), (0.0, 0.0))


class TestDrawTable(unittest.TestCase):
    SPEC = [("#", 2, "left"), ("Name", -1, "left"), ("Pts", 4, "right")]

    def test_layout_and_row_count(self):
        cv = Canvas(20, 5)
        rows = [[("1", "S"), ("Alpha", "S"), ("10", "S")],
                [("2", "S"), ("Beta", "S"), ("7", "S")]]
        used = widgets.draw_table(cv, 0, 0, 20, self.SPEC, rows,
                                  title="T", title_style="TS")
        self.assertEqual(used, 4)  # title + header + 2 rows
        self.assertEqual(row_text(cv, 0)[:1], "T")
        self.assertIn("─", row_text(cv, 0))          # rule after title
        self.assertIn("Name", row_text(cv, 1))
        self.assertEqual(row_text(cv, 1)[16:20], " Pts")  # right-aligned hdr
        self.assertEqual(row_text(cv, 2)[0], "1")
        self.assertIn("Alpha", row_text(cv, 2))
        self.assertEqual(row_text(cv, 2)[16:20], "  10")  # right-aligned cell

    def test_no_title_no_header(self):
        cv = Canvas(20, 3)
        spec = [("", 2, "left"), ("", -1, "left")]
        used = widgets.draw_table(cv, 0, 0, 20, spec, [[("x", ""), ("y", "")]])
        self.assertEqual(used, 1)  # data row only
        self.assertEqual(cv.grid[0][0].ch, "x")

    def test_flex_cell_truncated(self):
        cv = Canvas(14, 2)
        rows = [[("1", ""), ("a-very-long-name", ""), ("9", "")]]
        widgets.draw_table(cv, 0, 0, 14, self.SPEC, rows)
        body = row_text(cv, 1)
        self.assertIn("…", body)
        self.assertNotIn("long-name", body)

    def test_none_cell_skipped(self):
        cv = Canvas(20, 2)
        widgets.draw_table(cv, 0, 0, 20, self.SPEC,
                           [[None, ("only", ""), None]])
        self.assertEqual(cv.grid[1][0].ch, " ")
        self.assertIn("only", row_text(cv, 1))


class TestDrawCard(unittest.TestCase):
    def test_frame_title_right_and_inner(self):
        from tui.canvas import LIGHT
        cv = Canvas(30, 4)
        inner = widgets.draw_card(cv, 0, 0, 4, 30, title=" T ", right="FT")
        self.assertEqual(inner, (1, 2, 26))
        self.assertEqual(cv.grid[0][0].ch, LIGHT["tl"])
        self.assertEqual(cv.grid[0][29].ch, LIGHT["tr"])
        self.assertEqual(cv.grid[0][3].ch, "T")
        row = row_text(cv, 0)
        self.assertIn("FT", row)
        self.assertEqual(row.index("FT"), 30 - 2 - 2)  # right-aligned - 2

    def test_selection_chevrons(self):
        cv = Canvas(30, 4)
        widgets.draw_card(cv, 0, 0, 4, 30, selected=True, select_style="G")
        self.assertEqual(cv.grid[1][0].ch, "▸")
        self.assertEqual(cv.grid[2][0].ch, "▸")

    def test_title_truncated_clear_of_right(self):
        cv = Canvas(30, 4)
        widgets.draw_card(cv, 0, 0, 4, 30, title="x" * 40, right="LIVE")
        # title is truncated to w - title_reserve = 12 cols from c+2
        self.assertNotIn("x", row_text(cv, 0)[2 + 12:])
        self.assertIn("LIVE", row_text(cv, 0))


class TestDrawDuelRow(unittest.TestCase):
    def test_layout(self):
        cv = Canvas(40, 2)
        used = widgets.draw_duel_row(cv, 0, 0, 40, "Shots", 3, 1, "L", "R",
                                     track_style="T")
        self.assertEqual(used, 2)
        top = row_text(cv, 0)
        # left value right-aligned in 6 cols, right value at the right edge
        self.assertEqual(top[:6], "     3")
        self.assertEqual(top[34:40], "1     ")
        self.assertIn("Shots", top)
        # bar row: left fill 3/4, right fill 1/4 around center divider
        bar = row_text(cv, 1)
        self.assertIn("█", bar)
        self.assertIn("▏", bar)
        mid = (8 + 32) // 2  # (bar_l + bar_r) // 2 with val_w=6, gap=2
        self.assertEqual(cv.grid[1][mid].ch, "▏")
        self.assertEqual(cv.grid[1][mid - 1].ch, "█")  # left fill present

    def test_value_styles_default_to_bar_styles(self):
        cv = Canvas(40, 2)
        widgets.draw_duel_row(cv, 0, 0, 40, "x", 1, 1, "L", "R")
        self.assertEqual(cv.grid[0][5].style, "L")   # last cell of left value


class TestBracketLayout(unittest.TestCase):
    # 4 leaves -> 2 -> 1, fully wired
    SIZES = [4, 2, 1]
    FEEDERS = {(1, 0): (0, 1), (1, 1): (2, 3), (2, 0): (0, 1)}

    def test_geometry(self):
        w, h, colx, ypos = widgets.bracket_layout(self.SIZES, self.FEEDERS)
        self.assertEqual(w, 3 * 27 + 6)
        self.assertEqual(h, 4 * 4 + 6)
        self.assertEqual(colx, [2, 29, 56])

    def test_leaves_evenly_spaced_parents_at_midpoints(self):
        _, _, _, ypos = widgets.bracket_layout(self.SIZES, self.FEEDERS)
        self.assertEqual([ypos[(0, i)] for i in range(4)], [2, 6, 10, 14])
        self.assertEqual(ypos[(1, 0)], 4.0)   # midpoint of 2 and 6
        self.assertEqual(ypos[(1, 1)], 12.0)
        self.assertEqual(ypos[(2, 0)], 8.0)

    def test_crossing_feeders_reorder_leaves(self):
        feeders = {(1, 0): (3, 0), (1, 1): (1, 2), (2, 0): (0, 1)}
        _, _, _, ypos = widgets.bracket_layout([4, 2, 1], feeders)
        # walk order: 3, 0, 1, 2 -> leaf 3 sits on top
        self.assertEqual(ypos[(0, 3)], 2)
        self.assertEqual(ypos[(0, 0)], 6)

    def test_parentless_slot_fallback(self):
        _, _, _, ypos = widgets.bracket_layout([4, 2, 1], {})
        # no feeders: parents use the spaced fallback i*unit*2^ri + 2^ri
        self.assertEqual(ypos[(1, 0)], 2)
        self.assertEqual(ypos[(1, 1)], 10)

    def test_empty_leaves_fallback_height(self):
        _, h, _, _ = widgets.bracket_layout([0, 2, 1], {}, fallback_leaves=16)
        self.assertEqual(h, 16 * 4 + 6)


class TestDrawBracket(unittest.TestCase):
    def test_cells_and_connectors(self):
        seen = []

        def cell(cv, cy, cx, ri, i):
            seen.append((ri, i, cy, cx))
            cv.put(cy, cx, f"{ri}{i}")

        feeders = {(1, 0): (0, 1), (1, 1): (2, 3), (2, 0): (0, 1)}
        cv, colx, ypos = widgets.draw_bracket([4, 2, 1], feeders, cell,
                                              labels=["A", "B", "C"])
        self.assertEqual(len(seen), 7)          # every slot drawn
        text = "\n".join("".join(c.ch for c in row) for row in cv.grid)
        self.assertIn("A", text)                # labels
        self.assertIn("│", text)                # connector spine
        self.assertIn("╮", text)
        self.assertIn("├", text)
        # cell callback got the layout centers
        self.assertIn((2, 0, 8, colx[2]), seen)

    def test_canvas_is_returned_for_overdraw(self):
        cv, colx, ypos = widgets.draw_bracket([2, 1], {(1, 0): (0, 1)},
                                              lambda *a: None)
        cv.put(0, 0, "X")  # caller can draw more
        self.assertEqual(cv.grid[0][0].ch, "X")


class TestDrawConnector(unittest.TestCase):
    def test_shapes(self):
        cv = Canvas(20, 10)
        widgets.draw_connector(cv, 2, 6, 4, 5, 8, 12, "S")
        self.assertEqual(cv.grid[2][8].ch, "╮")
        self.assertEqual(cv.grid[6][8].ch, "╯")
        self.assertEqual(cv.grid[4][8].ch, "├")
        self.assertEqual(cv.grid[3][8].ch, "│")
        self.assertEqual(cv.grid[2][5].ch, "─")   # stub
        self.assertEqual(cv.grid[4][11].ch, "─")  # branch to parent


if __name__ == "__main__":
    unittest.main()
