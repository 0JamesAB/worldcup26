"""Theme registry and widget theming."""

import unittest

from tui import term, widgets
from tui.theme import Theme, get_theme, set_theme, styles


class ThemeCase(unittest.TestCase):
    def setUp(self):
        self._saved_theme = get_theme()
        self._saved_depth = term.get_color_depth()
        term.set_color_depth("truecolor")

    def tearDown(self):
        set_theme(self._saved_theme)
        term.set_color_depth(self._saved_depth)


class Loud(Theme):
    bg0 = (1, 1, 1)
    text = (250, 250, 250)


class TestRegistry(ThemeCase):
    def test_default(self):
        self.assertIs(get_theme(), self._saved_theme)

    def test_set_theme_affects_widgets(self):
        set_theme(Loud)
        self.assertEqual(widgets.base_style(),
                         term.bg(1, 1, 1) + term.fg(250, 250, 250))

    def test_kwarg_beats_registry(self):
        set_theme(Theme)
        self.assertEqual(widgets.base_style(theme=Loud),
                         term.bg(1, 1, 1) + term.fg(250, 250, 250))

    def test_subclass_inherits_base_colors(self):
        self.assertEqual(Loud.accent, Theme.accent)


class TestThemedWidgets(ThemeCase):
    def test_tab_bar_renders_labels(self):
        from tui.canvas import Canvas
        cv = Canvas(40, 1)
        widgets.tab_bar(cv, 0, 0, 40, [("1", "Live"), ("2", "Groups")], 0)
        row = "".join(c.ch for c in cv.grid[0])
        self.assertIn("1 Live", row)
        self.assertIn("2 Groups", row)

    def test_footer_renders_hints(self):
        from tui.canvas import Canvas
        cv = Canvas(40, 1)
        widgets.footer(cv, 0, 0, 40, [("q", "quit")], right="v1")
        row = "".join(c.ch for c in cv.grid[0])
        self.assertIn("q", row)
        self.assertIn("quit", row)
        self.assertIn("v1", row)


class TestTabBarExtents(unittest.TestCase):
    def test_extents_match_labels(self):
        from tui.canvas import Canvas
        from tui import widgets, term
        cv = Canvas(60, 1)
        ext = widgets.tab_bar(cv, 0, 0, 60, [("1", "Live"), ("2", "Groups")], 0)
        self.assertEqual(len(ext), 2)
        (x0, w0), (x1, w1) = ext
        self.assertEqual(x0, 0)
        self.assertEqual(w0, term.display_width(" 1 Live "))
        self.assertEqual(x1, w0 + 1)   # one-cell gap between tabs
        # extents line up with the rendered text
        row = "".join(c.ch for c in cv.grid[0])
        self.assertEqual(row[x1:x1 + w1], " 2 Groups ")


class TestTabBarOverflow(unittest.TestCase):
    def test_extents_clipped_to_bar_width(self):
        from tui.canvas import Canvas
        from tui import widgets
        cv = Canvas(40, 1)
        # bar is only 14 cols; second tab overflows, third is fully out
        ext = widgets.tab_bar(cv, 0, 0, 14,
                              [("1", "Live"), ("2", "Groups"), ("3", "More")], 0)
        self.assertEqual(len(ext), 3)
        for x, w in ext:
            if w > 0:                          # clickable extents stay in-bar
                self.assertLessEqual(x + w, 14)
        self.assertEqual(ext[2][1], 0)        # fully clipped tab: unclickable
        # nothing drawn past the bar region either
        row = "".join(c.ch for c in cv.grid[0])
        self.assertEqual(row[14:].strip(), "")


class TestStyles(ThemeCase):
    def test_combos_match_hand_concatenation(self):
        t = Theme
        st = styles(t)
        bg, fg = term.bg, term.fg
        expected = {
            "base": bg(*t.bg0) + fg(*t.text),
            "panel": bg(*t.bg1) + fg(*t.text),
            "panel_dim": bg(*t.bg1) + fg(*t.dim),
            "panel_faint": bg(*t.bg1) + fg(*t.faint),
            "panel_text_b": bg(*t.bg1) + fg(*t.text) + term.BOLD,
            "panel_dim_b": bg(*t.bg1) + fg(*t.dim) + term.BOLD,
            "panel_hl": bg(*t.bg1) + fg(*t.highlight),
            "panel_hl_b": bg(*t.bg1) + fg(*t.highlight) + term.BOLD,
            "raised": bg(*t.bg2) + fg(*t.text),
            "raised_dim": bg(*t.bg2) + fg(*t.dim),
            "chip": bg(*t.accent) + fg(*t.bg0) + term.BOLD,
            "hint": bg(*t.bg1) + fg(*t.faint),
        }
        self.assertEqual(set(expected), set(type(st).__slots__))
        for name, want in expected.items():
            self.assertEqual(getattr(st, name), want, name)

    def test_default_theme_is_installed_theme(self):
        set_theme(Loud)
        self.assertIs(styles(), styles(Loud))

    def test_cache_returns_same_object(self):
        self.assertIs(styles(Theme), styles(Theme))

    def test_depth_change_gives_different_strings(self):
        tc = styles(Theme)
        term.set_color_depth("256")
        st = styles(Theme)
        self.assertIsNot(st, tc)
        self.assertNotEqual(st.panel, tc.panel)
        self.assertEqual(st.panel, term.bg(*Theme.bg1) + term.fg(*Theme.text))
        term.set_color_depth("truecolor")
        self.assertIs(styles(Theme), tc)

    def test_subclass_gets_its_own_entry(self):
        st = styles(Loud)
        self.assertIsNot(st, styles(Theme))
        self.assertEqual(st.base, term.bg(1, 1, 1) + term.fg(250, 250, 250))


if __name__ == "__main__":
    unittest.main()
