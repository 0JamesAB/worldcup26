"""Generalized drawing widgets."""

import unittest

from puretui import term
from puretui.canvas import Canvas
from puretui.interact import ScrollState
from puretui import widgets


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


    def test_negative_frac_clamped(self):
        # regression: frac < 0 must not draw the track left of the bar
        cv = Canvas(20, 1)
        cv.put(0, 2, "AB")           # sentinel just left of the bar
        n = widgets.draw_hbar(cv, 0, 5, 10, -0.4, "F", "T")
        self.assertEqual(n, 0)
        self.assertEqual(cv.grid[0][2].ch, "A")
        self.assertEqual(cv.grid[0][3].ch, "B")
        self.assertEqual(row_text(cv, 0)[5:15], "░" * 10)
        self.assertEqual(cv.grid[0][15].ch, " ")   # nothing past the bar

    def test_negative_width_noop(self):
        cv = Canvas(10, 1)
        self.assertEqual(widgets.draw_hbar(cv, 0, 0, -5, 0.5, "F", "T"), 0)
        self.assertEqual(row_text(cv, 0), " " * 10)


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
        from puretui.canvas import LIGHT
        from puretui.layout import Rect
        cv = Canvas(30, 4)
        inner = widgets.draw_card(cv, 0, 0, 4, 30, title=" T ", right="FT")
        self.assertEqual(inner.rect, Rect(1, 2, 2, 26))
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


class TestSparkline(unittest.TestCase):
    def test_scaling_exact(self):
        self.assertEqual(widgets.sparkline(list(range(8)), lo=0, hi=7),
                         widgets.SPARK_CHARS)

    def test_default_range_from_values(self):
        self.assertEqual(widgets.sparkline([0, 7]), "\u2581\u2588")

    def test_flat_series(self):
        self.assertEqual(widgets.sparkline([5, 5, 5]), "\u2584" * 3)

    def test_clamping(self):
        self.assertEqual(widgets.sparkline([-10, 100], lo=0, hi=7),
                         "\u2581\u2588")

    def test_empty(self):
        self.assertEqual(widgets.sparkline([]), "")


class TestDrawSparkline(unittest.TestCase):
    def test_puts_and_returns_end_col(self):
        cv = Canvas(10, 1)
        end = widgets.draw_sparkline(cv, 0, 2, [0, 3.5, 7], "S", lo=0, hi=7)
        self.assertEqual(end, 5)
        self.assertEqual(row_text(cv, 0)[2:5], "\u2581\u2585\u2588")
        self.assertEqual(cv.grid[0][2].style, "S")


class TestSpinner(unittest.TestCase):
    def test_cycles_and_wraps(self):
        n = len(widgets.SPINNER_DOTS)
        self.assertEqual(widgets.spinner(0), widgets.SPINNER_DOTS[0])
        self.assertEqual(widgets.spinner(3), widgets.SPINNER_DOTS[3])
        self.assertEqual(widgets.spinner(n), widgets.SPINNER_DOTS[0])
        self.assertEqual(widgets.spinner(n + 2), widgets.SPINNER_DOTS[2])

    def test_alternate_frames(self):
        self.assertEqual(widgets.spinner(3, widgets.SPINNER_LINE), "\\")
        self.assertEqual(widgets.spinner(4, widgets.SPINNER_LINE), "|")


class TestDrawProgress(unittest.TestCase):
    def test_without_pct_full_width(self):
        cv = Canvas(10, 1)
        n = widgets.draw_progress(cv, 0, 0, 10, 0.5, "F", "T")
        self.assertEqual(n, 5)
        self.assertEqual(row_text(cv, 0), "\u2588" * 5 + "\u2591" * 5)

    def test_with_pct_geometry(self):
        cv = Canvas(15, 1)
        n = widgets.draw_progress(cv, 0, 0, 15, 0.5, "F", "T",
                                  show_pct=True, pct_style="P")
        self.assertEqual(n, 5)  # bar is width-5 = 10 wide, half filled
        row = row_text(cv, 0)
        self.assertEqual(row[:10], "\u2588" * 5 + "\u2591" * 5)
        self.assertEqual(row[10], " ")           # gap between bar and pct
        self.assertEqual(row[11:15], " 50%")     # right-aligned in last 4
        self.assertEqual(cv.grid[0][14].style, "P")

    def test_pct_full(self):
        cv = Canvas(12, 1)
        widgets.draw_progress(cv, 0, 0, 12, 1.0, "F", show_pct=True)
        self.assertEqual(row_text(cv, 0)[8:12], "100%")

    def test_pct_zero(self):
        cv = Canvas(12, 1)
        n = widgets.draw_progress(cv, 0, 0, 12, 0.0, "F", "T", show_pct=True)
        self.assertEqual(n, 0)
        self.assertEqual(row_text(cv, 0)[8:12], "  0%")

    def test_narrow_width_stays_inside_budget(self):
        # width < 5 leaves no room for the pct: nothing may be drawn
        # past c + width.
        cv = Canvas(10, 1)
        cv.put(0, 3, "XXXX", "N")  # neighbors just past the 3-wide budget
        widgets.draw_progress(cv, 0, 0, 3, 0.5, "F", show_pct=True)
        self.assertEqual(row_text(cv, 0)[3:7], "XXXX")

    def test_frac_clamped(self):
        cv = Canvas(12, 1)
        widgets.draw_progress(cv, 0, 0, 12, 25.0, "F", show_pct=True)
        self.assertEqual(row_text(cv, 0)[8:12], "100%")  # not "2500%"
        cv2 = Canvas(12, 1)
        widgets.draw_progress(cv2, 0, 0, 12, -3.0, "F", "T", show_pct=True)
        self.assertEqual(row_text(cv2, 0)[8:12], "  0%")


class TestDrawBadge(unittest.TestCase):
    def test_padding_and_return_col(self):
        cv = Canvas(10, 1)
        end = widgets.draw_badge(cv, 0, 1, "OK", "S")
        self.assertEqual(end, 5)
        self.assertEqual(row_text(cv, 0)[1:5], " OK ")
        for x in range(1, 5):
            self.assertEqual(cv.grid[0][x].style, "S")


class TestDrawRule(unittest.TestCase):
    def test_plain_rule(self):
        cv = Canvas(12, 1)
        widgets.draw_rule(cv, 0, 1, 10, style="S")
        self.assertEqual(row_text(cv, 0)[1:11], "\u2500" * 10)
        self.assertEqual(cv.grid[0][0].ch, " ")
        self.assertEqual(cv.grid[0][11].ch, " ")

    def test_title_centered(self):
        cv = Canvas(20, 1)
        widgets.draw_rule(cv, 0, 0, 20, title="Hi", style="S")
        row = row_text(cv, 0)
        # " Hi " (4 wide) centered: starts at (20 - 4) // 2 = 8
        self.assertEqual(row[8:12], " Hi ")
        self.assertEqual(row[:8], "\u2500" * 8)
        self.assertEqual(row[12:20], "\u2500" * 8)

    def test_title_style_defaults_to_style(self):
        cv = Canvas(20, 1)
        widgets.draw_rule(cv, 0, 0, 20, title="Hi", style="S")
        self.assertEqual(cv.grid[0][9].style, "S")
        cv2 = Canvas(20, 1)
        widgets.draw_rule(cv2, 0, 0, 20, title="Hi", style="S",
                          title_style="TS")
        self.assertEqual(cv2.grid[0][9].style, "TS")
        self.assertEqual(cv2.grid[0][0].style, "S")

    def test_title_wider_than_width_truncates(self):
        cv = Canvas(8, 1)
        widgets.draw_rule(cv, 0, 0, 6, title="abcdefghij")
        row = row_text(cv, 0)
        self.assertIn("\u2026", row[:6])
        self.assertNotIn("f", row)
        self.assertEqual(cv.grid[0][6].ch, " ")  # nothing past the rule

    def test_zero_or_negative_width_draws_nothing(self):
        cv = Canvas(8, 1)
        widgets.draw_rule(cv, 0, 2, 0, title="hi")
        widgets.draw_rule(cv, 0, 2, -3, title="hi")
        self.assertEqual(row_text(cv, 0), " " * 8)


class TestColLayout(unittest.TestCase):
    SPEC = [("#", 2, "left"), ("Name", -1, "left"), ("Pts", 4, "right")]

    def test_flex_absorbs_leftover(self):
        self.assertEqual(widgets.col_layout(self.SPEC, 20),
                         [(0, 2), (2, 14), (16, 4)])

    def test_all_fixed(self):
        spec = [("a", 3, "left"), ("b", 5, "left")]
        self.assertEqual(widgets.col_layout(spec, 20), [(0, 3), (3, 5)])

    def test_flex_clamped_to_zero(self):
        # fixed columns already exceed w: the flex column gets width 0
        self.assertEqual(widgets.col_layout(self.SPEC, 5),
                         [(0, 2), (2, 0), (2, 4)])

    def test_matches_draw_table_placement(self):
        # the extents are exactly where draw_table renders each column
        cv = Canvas(26, 3)
        c = 3
        rows = [[("1", ""), ("Alpha", ""), ("10", "")]]
        widgets.draw_table(cv, 0, c, 20, self.SPEC, rows)
        cols = widgets.col_layout(self.SPEC, 20)
        hdr_row = row_text(cv, 0)
        for (hdr, _, align), (x, cw) in zip(self.SPEC, cols):
            if align == "left":
                self.assertEqual(hdr_row[c + x:c + x + len(hdr)], hdr)
            else:
                self.assertEqual(
                    hdr_row[c + x + cw - len(hdr):c + x + cw], hdr)
        body = row_text(cv, 1)
        self.assertEqual(body[c + cols[0][0]], "1")
        self.assertEqual(body[c + cols[1][0]:c + cols[1][0] + 5], "Alpha")
        x, cw = cols[2]
        self.assertEqual(body[c + x:c + x + cw], "  10")


class TestDrawTextPane(unittest.TestCase):
    LINES = ["aaa bbb ccc", "dd"]  # wraps at w=7 to: aaa bbb / ccc / dd

    def test_wrap_total_and_extent(self):
        cv = Canvas(10, 4)
        sc = ScrollState()
        total = widgets.draw_text_pane(cv, 0, 0, 4, 7, self.LINES, sc)
        self.assertEqual(total, 3)
        self.assertEqual((sc.content, sc.viewport), (3, 4))
        self.assertEqual(row_text(cv, 0).rstrip(), "aaa bbb")
        self.assertEqual(row_text(cv, 1).rstrip(), "ccc")
        self.assertEqual(row_text(cv, 2).rstrip(), "dd")
        self.assertEqual(row_text(cv, 3).strip(), "")

    def test_scroll_offset_windows_content(self):
        cv = Canvas(10, 2)
        sc = ScrollState(content=3, viewport=2, offset=1)
        widgets.draw_text_pane(cv, 0, 0, 2, 7, self.LINES, sc)
        self.assertEqual(row_text(cv, 0).rstrip(), "ccc")
        self.assertEqual(row_text(cv, 1).rstrip(), "dd")

    def test_stale_offset_reclamped(self):
        cv = Canvas(10, 2)
        sc = ScrollState(content=99, viewport=2, offset=50)
        widgets.draw_text_pane(cv, 0, 0, 2, 7, self.LINES, sc)
        self.assertEqual(sc.offset, 1)  # max_offset for 3 lines in 2 rows
        self.assertEqual(row_text(cv, 0).rstrip(), "ccc")

    def test_entry_style_overrides_default(self):
        cv = Canvas(10, 2)
        sc = ScrollState()
        widgets.draw_text_pane(cv, 0, 0, 2, 8, ["plain", ("hot", "H")],
                               sc, style="D")
        self.assertEqual(cv.grid[0][0].style, "D")
        self.assertEqual(cv.grid[1][0].style, "H")

    def test_pct_right_aligned_on_overflow(self):
        cv = Canvas(12, 2)
        sc = ScrollState(content=3, viewport=2, offset=1)
        widgets.draw_text_pane(cv, 0, 2, 2, 10, self.LINES, sc,
                               pct=True, pct_style="P")
        row = row_text(cv, 0)
        self.assertEqual(row[8:12], "100%")  # right edge is c + w = 12
        self.assertEqual(cv.grid[0][8].style, "P")

    def test_pct_omitted_when_content_fits(self):
        cv = Canvas(12, 4)
        sc = ScrollState()
        widgets.draw_text_pane(cv, 0, 0, 4, 10, ["one", "two"], sc,
                               pct=True, pct_style="P")
        self.assertNotIn("%", row_text(cv, 0))

    def test_nowrap_truncates_long_lines(self):
        cv = Canvas(12, 2)
        sc = ScrollState()
        total = widgets.draw_text_pane(cv, 0, 0, 2, 6,
                                       ["a-very-long-line"], sc, wrap=False)
        self.assertEqual(total, 1)
        row = row_text(cv, 0)
        self.assertIn("…", row[:6])
        self.assertEqual(row[6:], " " * 6)  # nothing past c + w


class TestDrawMeterRows(unittest.TestCase):
    ITEMS = [("cpu", 0.30), ("mem", 0.70), ("disk", 0.95)]
    STYLES = ("L", "M", "H")

    def test_threshold_style_selection(self):
        cv = Canvas(20, 3)
        used = widgets.draw_meter_rows(cv, 0, 0, 20, self.ITEMS,
                                       styles=self.STYLES)
        self.assertEqual(used, 3)
        # label_w defaults to the widest label ("disk") + 1 = 5
        for i, sty in enumerate(self.STYLES):
            self.assertEqual(cv.grid[i][5].ch, "█")
            self.assertEqual(cv.grid[i][5].style, sty)

    def test_threshold_boundaries_are_exclusive_below(self):
        cv = Canvas(20, 2)
        widgets.draw_meter_rows(cv, 0, 0, 20, [("a", 0.6), ("b", 0.8)],
                                styles=self.STYLES)
        self.assertEqual(cv.grid[0][2].style, "M")  # 0.6 is not below 0.6
        self.assertEqual(cv.grid[1][2].style, "H")

    def test_threshold_pair_style_override(self):
        cv = Canvas(20, 1)
        widgets.draw_meter_rows(cv, 0, 0, 20, [("a", 0.1)],
                                thresholds=((0.6, "X"), (0.8, None)),
                                styles=self.STYLES)
        self.assertEqual(cv.grid[0][2].style, "X")

    def test_labels_and_explicit_label_w(self):
        cv = Canvas(20, 1)
        widgets.draw_meter_rows(cv, 0, 0, 20, [("longlabel", 1.0)],
                                label_w=5, styles=self.STYLES,
                                label_style="LS")
        row = row_text(cv, 0)
        self.assertIn("…", row[:5])       # label truncated to label_w
        self.assertEqual(cv.grid[0][0].style, "LS")
        self.assertEqual(row[5:20], "█" * 15)  # bar starts at label_w

    def test_default_styles_are_plain(self):
        cv = Canvas(12, 1)
        used = widgets.draw_meter_rows(cv, 0, 0, 12, [("a", 0.5)])
        self.assertEqual(used, 1)
        self.assertEqual(cv.grid[0][2].ch, "█")
        self.assertEqual(cv.grid[0][2].style, "")


if __name__ == "__main__":
    unittest.main()
