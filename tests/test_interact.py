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


class TestHitMap(unittest.TestCase):
    def setUp(self):
        from tui.interact import HitMap
        self.hm = HitMap()

    def test_empty_lookup(self):
        self.assertIsNone(self.hm.lookup(0, 0))

    def test_basic_region(self):
        self.hm.add(2, 10, 3, 20, ("view", "live"))
        self.assertEqual(self.hm.lookup(2, 10), ("view", "live"))
        self.assertEqual(self.hm.lookup(4, 29), ("view", "live"))
        self.assertIsNone(self.hm.lookup(5, 10))   # row past extent
        self.assertIsNone(self.hm.lookup(2, 30))   # col past extent
        self.assertIsNone(self.hm.lookup(1, 10))

    def test_last_added_wins_overlap(self):
        self.hm.add(0, 0, 10, 10, "under")
        self.hm.add(2, 2, 2, 2, "over")
        self.assertEqual(self.hm.lookup(3, 3), "over")
        self.assertEqual(self.hm.lookup(0, 0), "under")

    def test_zero_size_ignored(self):
        self.hm.add(0, 0, 0, 5, "a")
        self.hm.add(0, 0, 5, 0, "b")
        self.assertEqual(len(self.hm), 0)

    def test_clear(self):
        self.hm.add(0, 0, 1, 1, "a")
        self.hm.clear()
        self.assertIsNone(self.hm.lookup(0, 0))
        self.assertEqual(len(self.hm), 0)


class _FakeMouseEvent:
    """MouseEvent-shaped object; LineEdit must pass it through."""

    def __init__(self):
        self.row, self.col, self.button, self.kind = 0, 0, "left", "press"


class TestLineEditTyping(unittest.TestCase):
    def setUp(self):
        from tui.interact import LineEdit
        self.ed = LineEdit()

    def type_all(self, s):
        for ch in s:
            self.assertTrue(self.ed.handle_key(ch))

    def test_empty(self):
        self.assertEqual(self.ed.text, "")
        self.assertEqual(self.ed.cursor, 0)

    def test_init_text_puts_cursor_at_end(self):
        from tui.interact import LineEdit
        ed = LineEdit("abc")
        self.assertEqual(ed.text, "abc")
        self.assertEqual(ed.cursor, 3)

    def test_typing_appends_and_advances(self):
        self.type_all("hi there")
        self.assertEqual(self.ed.text, "hi there")
        self.assertEqual(self.ed.cursor, 8)

    def test_insert_mid_buffer(self):
        self.type_all("ac")
        self.ed.handle_key("LEFT")
        self.assertTrue(self.ed.handle_key("b"))
        self.assertEqual(self.ed.text, "abc")
        self.assertEqual(self.ed.cursor, 2)

    def test_insert_at_start(self):
        self.type_all("bc")
        self.ed.handle_key("HOME")
        self.ed.handle_key("a")
        self.assertEqual(self.ed.text, "abc")
        self.assertEqual(self.ed.cursor, 1)

    def test_unicode_chars_are_just_chars(self):
        # Wide/emoji chars count as one char here; width is the
        # widget's problem, not the editor state's.
        for ch in ("日", "本", "🎉"):
            self.assertTrue(self.ed.handle_key(ch))
        self.assertEqual(self.ed.text, "日本🎉")
        self.assertEqual(self.ed.cursor, 3)
        self.ed.handle_key("LEFT")
        self.ed.handle_key("BACKSPACE")
        self.assertEqual(self.ed.text, "日🎉")
        self.assertEqual(self.ed.cursor, 1)

    def test_clear(self):
        self.type_all("abc")
        self.ed.clear()
        self.assertEqual(self.ed.text, "")
        self.assertEqual(self.ed.cursor, 0)


class TestLineEditEditingKeys(unittest.TestCase):
    def setUp(self):
        from tui.interact import LineEdit
        self.ed = LineEdit("abcd")

    def test_backspace_at_end(self):
        self.assertTrue(self.ed.handle_key("BACKSPACE"))
        self.assertEqual(self.ed.text, "abc")
        self.assertEqual(self.ed.cursor, 3)

    def test_backspace_mid_buffer(self):
        self.ed.cursor = 2
        self.ed.handle_key("BACKSPACE")
        self.assertEqual(self.ed.text, "acd")
        self.assertEqual(self.ed.cursor, 1)

    def test_backspace_at_start_consumed_noop(self):
        self.ed.cursor = 0
        self.assertTrue(self.ed.handle_key("BACKSPACE"))
        self.assertEqual(self.ed.text, "abcd")
        self.assertEqual(self.ed.cursor, 0)

    def test_delete_mid_buffer(self):
        self.ed.cursor = 1
        self.assertTrue(self.ed.handle_key("DELETE"))
        self.assertEqual(self.ed.text, "acd")
        self.assertEqual(self.ed.cursor, 1)

    def test_delete_at_end_consumed_noop(self):
        self.assertTrue(self.ed.handle_key("DELETE"))
        self.assertEqual(self.ed.text, "abcd")
        self.assertEqual(self.ed.cursor, 4)

    def test_delete_everything_forward(self):
        self.ed.handle_key("HOME")
        for _ in range(6):  # two extra past empty
            self.ed.handle_key("DELETE")
        self.assertEqual(self.ed.text, "")
        self.assertEqual(self.ed.cursor, 0)

    def test_left_right_clamped(self):
        for _ in range(10):
            self.assertTrue(self.ed.handle_key("LEFT"))
        self.assertEqual(self.ed.cursor, 0)
        for _ in range(10):
            self.assertTrue(self.ed.handle_key("RIGHT"))
        self.assertEqual(self.ed.cursor, 4)

    def test_home_end(self):
        self.assertTrue(self.ed.handle_key("HOME"))
        self.assertEqual(self.ed.cursor, 0)
        self.assertTrue(self.ed.handle_key("END"))
        self.assertEqual(self.ed.cursor, 4)

    def test_key_constants_match_term(self):
        # LineEdit matches literal strings so interact stays term-free;
        # this pins them to the real Key constants.
        from tui.term import Key
        for k in (Key.LEFT, Key.RIGHT, Key.HOME, Key.END,
                  Key.BACKSPACE, Key.DELETE):
            self.assertTrue(self.ed.handle_key(k))


class TestLineEditPassthrough(unittest.TestCase):
    def setUp(self):
        from tui.interact import LineEdit
        self.ed = LineEdit("abc")
        self.ed.cursor = 1

    def assert_unconsumed(self, key):
        self.assertFalse(self.ed.handle_key(key))
        self.assertEqual(self.ed.text, "abc")
        self.assertEqual(self.ed.cursor, 1)

    def test_non_str_keys_fall_through(self):
        self.assert_unconsumed(_FakeMouseEvent())
        self.assert_unconsumed(None)
        self.assert_unconsumed(7)

    def test_named_keys_fall_through(self):
        for key in ("ENTER", "ESC", "TAB", "SHIFT_TAB", "UP", "DOWN",
                    "PGUP", "PGDN", "CTRL_R"):
            self.assert_unconsumed(key)

    def test_control_chars_fall_through(self):
        self.assert_unconsumed("\x1b")
        self.assert_unconsumed("\n")
        self.assert_unconsumed("\t")

    def test_multichar_strings_fall_through(self):
        self.assert_unconsumed("ab")
        self.assert_unconsumed("")

    def test_space_is_printable(self):
        self.assertTrue(self.ed.handle_key(" "))
        self.assertEqual(self.ed.text, "a bc")
        self.assertEqual(self.ed.cursor, 2)
