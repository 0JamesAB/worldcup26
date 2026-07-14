"""Composable Style objects (puretui/styles.py)."""

import unittest

from puretui import term
from puretui.styles import Style


class StyleCase(unittest.TestCase):
    def setUp(self):
        self._saved_depth = term.get_color_depth()
        term.set_color_depth("truecolor")

    def tearDown(self):
        term.set_color_depth(self._saved_depth)


class TestColorParsing(StyleCase):
    def test_hex_fg(self):
        self.assertEqual(Style(fg="#ff0000").fg, (255, 0, 0))

    def test_hex_without_hash(self):
        self.assertEqual(Style(fg="00ff7f").fg, (0, 255, 127))

    def test_hex_bg(self):
        self.assertEqual(Style(bg="#141821").bg, (20, 24, 33))

    def test_tuple_fg(self):
        self.assertEqual(Style(fg=(10, 20, 30)).fg, (10, 20, 30))

    def test_list_fg_normalized_to_tuple(self):
        self.assertEqual(Style(fg=[10, 20, 30]).fg, (10, 20, 30))

    def test_invalid_hex_raises(self):
        with self.assertRaises(ValueError):
            Style(fg="notahex")
        with self.assertRaises(ValueError):
            Style(fg="#12345")
        with self.assertRaises(ValueError):
            Style(fg="zzzzzz", attrs=("bold",))

    def test_malformed_tuple_raises(self):
        with self.assertRaises(ValueError):
            Style(fg=(1, 2))
        with self.assertRaises(ValueError):
            Style(bg=(1, 2, 3, 4))

    def test_unknown_attr_raises(self):
        with self.assertRaises(ValueError):
            Style(attrs=("shiny",))


class TestChaining(StyleCase):
    def test_bold_returns_new_object(self):
        s = Style(fg=(1, 2, 3))
        b = s.bold()
        self.assertIsNot(b, s)
        self.assertEqual(s.attrs, frozenset())
        self.assertEqual(b.attrs, frozenset(("bold",)))
        self.assertEqual(b.fg, (1, 2, 3))

    def test_chain_accumulates(self):
        s = Style().bold().underline().dim()
        self.assertEqual(s.attrs, frozenset(("bold", "underline", "dim")))

    def test_every_attr_method(self):
        for name in ("bold", "dim", "italic", "underline", "reverse", "blink"):
            s = getattr(Style(), name)()
            self.assertEqual(s.attrs, frozenset((name,)))

    def test_on_replaces_bg_only(self):
        s = Style(fg="#ff0000", bg=(0, 0, 0)).bold()
        t = s.on("#00ff00")
        self.assertIsNot(t, s)
        self.assertEqual(t.bg, (0, 255, 0))
        self.assertEqual(t.fg, (255, 0, 0))
        self.assertEqual(t.attrs, frozenset(("bold",)))
        self.assertEqual(s.bg, (0, 0, 0))  # original unchanged


class TestMerge(StyleCase):
    def test_other_colors_win(self):
        a = Style(fg=(1, 1, 1), bg=(2, 2, 2))
        b = Style(fg=(9, 9, 9))
        m = a + b
        self.assertEqual(m.fg, (9, 9, 9))
        self.assertEqual(m.bg, (2, 2, 2))  # b.bg unset -> a's kept

    def test_attrs_union(self):
        m = Style().bold() + Style().underline()
        self.assertEqual(m.attrs, frozenset(("bold", "underline")))

    def test_or_is_add(self):
        a = Style(fg=(1, 1, 1)).bold()
        b = Style(bg=(2, 2, 2)).dim()
        self.assertEqual(a | b, a + b)

    def test_add_non_style_raises(self):
        with self.assertRaises(TypeError):
            Style() + "bold"


class TestRendering(StyleCase):
    def test_str_prefix(self):
        s = Style(fg=(255, 0, 0), bg=(0, 0, 32)).bold()
        self.assertEqual(str(s),
                         term.fg(255, 0, 0) + term.bg(0, 0, 32) + term.BOLD)

    def test_call_wraps_with_reset(self):
        s = Style(fg=(255, 0, 0))
        self.assertEqual(s("hi"), term.fg(255, 0, 0) + "hi" + term.RESET)

    def test_empty_style(self):
        self.assertEqual(str(Style()), "")
        self.assertEqual(Style()("hi"), "hi" + term.RESET)

    def test_mono_drops_colors_keeps_attrs(self):
        term.set_color_depth("mono")
        s = Style(fg=(255, 0, 0), bg=(0, 0, 0)).bold().underline()
        self.assertEqual(str(s), term.BOLD + term.UNDERLINE)

    def test_depth_respected_at_render_time(self):
        s = Style(fg=(100, 150, 200))
        term.set_color_depth("256")
        self.assertEqual(str(s), term.fg(100, 150, 200))
        self.assertIn(";5;", str(s))


class TestEquality(StyleCase):
    def test_hex_equals_tuple(self):
        self.assertEqual(Style(fg="#ff0000"), Style(fg=(255, 0, 0)))

    def test_hash_matches_eq(self):
        a = Style(fg="#ff0000").bold()
        b = Style(fg=(255, 0, 0)).bold()
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)

    def test_attr_difference_unequal(self):
        self.assertNotEqual(Style().bold(), Style().dim())
        self.assertNotEqual(Style(fg=(1, 2, 3)), Style(bg=(1, 2, 3)))

    def test_not_equal_to_other_types(self):
        self.assertNotEqual(Style(), "")

    def test_repr(self):
        r = repr(Style(fg="#ff0000").bold())
        self.assertIn("Style(", r)
        self.assertIn("(255, 0, 0)", r)
        self.assertIn("bold", r)


if __name__ == "__main__":
    unittest.main()
