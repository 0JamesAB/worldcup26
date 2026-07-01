"""Selection and scroll state helpers."""

import unittest

from tui.interact import ListState, ScrollState


class TestListStateBasics(unittest.TestCase):
    def test_empty(self):
        ls = ListState()
        self.assertEqual(ls.count, 0)
        self.assertEqual(ls.sel, 0)
        ls.move(1)
        ls.move(-1)
        ls.end()
        ls.home()
        self.assertEqual(ls.sel, 0)
        self.assertEqual(ls.window(5), (0, 0))

    def test_init_clamps(self):
        self.assertEqual(ListState(5, 99).sel, 4)
        self.assertEqual(ListState(5, -3).sel, 0)
        self.assertEqual(ListState(-2, 3).count, 0)
        self.assertEqual(ListState(-2, 3).sel, 0)

    def test_single_item(self):
        ls = ListState(1)
        ls.move(1)
        self.assertEqual(ls.sel, 0)
        ls.move(-1)
        self.assertEqual(ls.sel, 0)
        ls.end()
        self.assertEqual(ls.sel, 0)
        self.assertEqual(ls.window(10), (0, 1))

    def test_move_clamps_at_edges(self):
        ls = ListState(10)
        ls.move(-5)
        self.assertEqual(ls.sel, 0)
        ls.move(3)
        self.assertEqual(ls.sel, 3)
        ls.move(100)
        self.assertEqual(ls.sel, 9)

    def test_home_end(self):
        ls = ListState(7, 3)
        ls.end()
        self.assertEqual(ls.sel, 6)
        ls.home()
        self.assertEqual(ls.sel, 0)

    def test_page_beyond_ends(self):
        ls = ListState(20, 10)
        ls.page(5, 6)  # way past the end
        self.assertEqual(ls.sel, 19)
        ls.page(-5, 6)  # way past the start
        self.assertEqual(ls.sel, 0)
        ls.page(1, 6)
        self.assertEqual(ls.sel, 6)

    def test_sel_clamp_on_shrink(self):
        ls = ListState(10, 9)
        ls.set_count(4)
        self.assertEqual(ls.sel, 3)
        ls.set_count(0)
        self.assertEqual(ls.sel, 0)
        ls.set_count(6)
        self.assertEqual(ls.sel, 0)


class TestListStateWindow(unittest.TestCase):
    def test_count_smaller_than_visible(self):
        ls = ListState(3, 2)
        self.assertEqual(ls.window(10), (0, 3))

    def test_visible_nonpositive(self):
        ls = ListState(5, 2)
        self.assertEqual(ls.window(0), (0, 0))
        self.assertEqual(ls.window(-1), (0, 0))

    def test_stable_while_sel_inside_view(self):
        ls = ListState(20)
        self.assertEqual(ls.window(5), (0, 5))
        for i in range(5):
            ls.sel = i
            self.assertEqual(ls.window(5), (0, 5))

    def test_scrolls_down_minimally(self):
        ls = ListState(20)
        ls.window(5)
        ls.sel = 5  # one past the bottom
        self.assertEqual(ls.window(5), (1, 6))
        ls.sel = 12
        self.assertEqual(ls.window(5), (8, 13))

    def test_scrolls_up_minimally(self):
        ls = ListState(20, 12)
        self.assertEqual(ls.window(5), (8, 13))
        ls.sel = 7  # one above the top
        self.assertEqual(ls.window(5), (7, 12))
        ls.sel = 9  # back inside: window must not move
        self.assertEqual(ls.window(5), (7, 12))

    def test_window_at_edges(self):
        ls = ListState(20)
        ls.end()
        self.assertEqual(ls.window(5), (15, 20))
        ls.home()
        self.assertEqual(ls.window(5), (0, 5))

    def test_offset_reclamps_on_shrink(self):
        ls = ListState(20)
        ls.end()
        ls.window(5)
        ls.set_count(8)
        self.assertEqual(ls.window(5), (3, 8))
        ls.set_count(3)
        self.assertEqual(ls.window(5), (0, 3))

    def test_window_after_visible_change(self):
        ls = ListState(20, 12)
        ls.window(5)
        # Bigger viewport still contains sel; offset stays put.
        self.assertEqual(ls.window(10), (8, 18))
        # Smaller viewport must pull sel back into view.
        start, stop = ls.window(3)
        self.assertLessEqual(start, ls.sel)
        self.assertLess(ls.sel, stop)
        self.assertEqual(stop - start, 3)


class TestScrollState(unittest.TestCase):
    def test_defaults(self):
        ss = ScrollState()
        self.assertEqual(ss.offset, 0)
        self.assertEqual(ss.max_offset, 0)
        self.assertEqual(ss.pct, 0)
        self.assertTrue(ss.at_top)
        self.assertTrue(ss.at_bottom)

    def test_init_clamps_offset(self):
        ss = ScrollState(content=10, viewport=4, offset=99)
        self.assertEqual(ss.offset, 6)
        self.assertEqual(ScrollState(10, 4, -3).offset, 0)

    def test_scroll_clamps(self):
        ss = ScrollState(content=30, viewport=10)
        ss.scroll(5)
        self.assertEqual(ss.offset, 5)
        ss.scroll(100)
        self.assertEqual(ss.offset, 20)
        ss.scroll(-100)
        self.assertEqual(ss.offset, 0)

    def test_page_beyond_ends(self):
        ss = ScrollState(content=25, viewport=10)
        ss.page(1)
        self.assertEqual(ss.offset, 10)
        ss.page(1)
        self.assertEqual(ss.offset, 15)
        ss.page(1)  # past the end
        self.assertEqual(ss.offset, 15)
        ss.page(-2)
        self.assertEqual(ss.offset, 0)
        ss.page(-1)  # past the start
        self.assertEqual(ss.offset, 0)

    def test_home_end(self):
        ss = ScrollState(content=30, viewport=10)
        ss.end()
        self.assertEqual(ss.offset, 20)
        self.assertTrue(ss.at_bottom)
        self.assertFalse(ss.at_top)
        ss.home()
        self.assertEqual(ss.offset, 0)
        self.assertTrue(ss.at_top)
        self.assertFalse(ss.at_bottom)

    def test_clamp_on_extent_change(self):
        ss = ScrollState(content=100, viewport=10)
        ss.end()
        self.assertEqual(ss.offset, 90)
        ss.set_extent(30, 10)
        self.assertEqual(ss.offset, 20)
        ss.set_extent(5, 10)  # content fits: offset collapses to 0
        self.assertEqual(ss.offset, 0)
        self.assertEqual(ss.max_offset, 0)

    def test_viewport_grow_reclamps(self):
        ss = ScrollState(content=30, viewport=10, offset=20)
        ss.set_extent(30, 25)
        self.assertEqual(ss.offset, 5)

    def test_pct_when_content_fits(self):
        ss = ScrollState(content=5, viewport=10, offset=0)
        self.assertEqual(ss.pct, 0)
        ss = ScrollState(content=10, viewport=10)
        self.assertEqual(ss.pct, 0)

    def test_pct_rounding(self):
        ss = ScrollState(content=30, viewport=10)
        self.assertEqual(ss.pct, 0)
        ss.scroll(10)
        self.assertEqual(ss.pct, 50)
        ss.end()
        self.assertEqual(ss.pct, 100)
        # 7 of 21 -> 33.33 -> 33; 14 of 21 -> 66.67 -> 67
        ss.set_extent(31, 10)
        ss.home()
        ss.scroll(7)
        self.assertEqual(ss.pct, 33)
        ss.scroll(7)
        self.assertEqual(ss.pct, 67)

    def test_at_top_bottom_when_all_fits(self):
        ss = ScrollState(content=3, viewport=10)
        self.assertTrue(ss.at_top)
        self.assertTrue(ss.at_bottom)


if __name__ == "__main__":
    unittest.main()
