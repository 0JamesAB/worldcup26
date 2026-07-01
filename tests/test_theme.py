"""Theme registry and widget theming."""

import unittest

from tui import term, widgets
from tui.theme import Theme, get_theme, set_theme


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


if __name__ == "__main__":
    unittest.main()
