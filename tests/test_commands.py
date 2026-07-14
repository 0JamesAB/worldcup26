"""Command palette kit: CommandSet, Palette, and the drawing ports."""

import unittest

from puretui import term
from puretui.canvas import Canvas
from puretui.commands import (CommandSet, Palette, draw_palette_bar,
                          draw_palette_menu)
from puretui.interact import HitMap
from puretui.term import Key
from puretui.testing import render_plain
from puretui.theme import Theme


def make_commands(log=None):
    """A small command set exercising every spec shape."""
    log = [] if log is None else log

    def runner(name, result=None):
        def run(arg):
            log.append((name, arg))
            return f"{name} {arg}".strip() if result is None else result
        return run

    def complete_name(arg):
        out = [{"text": f"hello {n}", "label": n, "hint": "--" + n,
                "kind": "arg"}
               for n in ("ana", "bob", "cara") if arg == "" or arg in n]
        return ("Names", out)

    specs = [
        {"name": "hello", "aliases": ["hi", "greet"], "syntax": "hello [name]",
         "desc": "say hello", "run": runner("hello"), "complete": complete_name},
        {"name": "help", "aliases": ["h"], "syntax": "help",
         "desc": "keys & commands", "run": runner("help"), "complete": None},
        {"name": "quit", "aliases": ["q", "exit"], "syntax": "quit",
         "desc": "exit", "run": runner("quit", result=""), "complete": None},
        {"name": "halt", "aliases": [], "syntax": "halt",
         "desc": "stop", "run": runner("halt"), "complete": None},
    ]
    return CommandSet(specs), log


class FakeApp:
    def __init__(self):
        self.capture = None


class TestFind(unittest.TestCase):
    def setUp(self):
        self.cs, _ = make_commands()

    def test_exact_name(self):
        self.assertEqual(self.cs.find("hello")["name"], "hello")

    def test_alias(self):
        self.assertEqual(self.cs.find("q")["name"], "quit")
        self.assertEqual(self.cs.find("exit")["name"], "quit")

    def test_exact_alias_beats_prefix_ambiguity(self):
        # "h" prefixes hello/help/halt but is an exact alias of help
        self.assertEqual(self.cs.find("h")["name"], "help")

    def test_unique_prefix_of_name(self):
        self.assertEqual(self.cs.find("hell")["name"], "hello")
        self.assertEqual(self.cs.find("ha")["name"], "halt")
        self.assertEqual(self.cs.find("qu")["name"], "quit")

    def test_unique_prefix_of_alias(self):
        self.assertEqual(self.cs.find("gr")["name"], "hello")  # greet

    def test_ambiguous_prefix(self):
        self.assertIsNone(self.cs.find("hel"))  # hello | help
        self.assertIsNone(self.cs.find("he"))

    def test_unknown(self):
        self.assertIsNone(self.cs.find("zzz"))

    def test_case_insensitive(self):
        self.assertEqual(self.cs.find("HELLO")["name"], "hello")
        self.assertEqual(self.cs.find("Q")["name"], "quit")


class TestCompletions(unittest.TestCase):
    def setUp(self):
        self.cs, _ = make_commands()

    def test_empty_buffer_lists_every_command(self):
        title, sugg = self.cs.completions("")
        self.assertEqual(title, "Commands")
        self.assertEqual([s["text"] for s in sugg],
                         ["hello ", "help", "quit", "halt"])
        self.assertTrue(all(s["kind"] == "cmd" for s in sugg))
        self.assertEqual(sugg[0]["label"], ":hello [name]")
        self.assertEqual(sugg[0]["hint"], "say hello")

    def test_arg_taking_commands_get_a_trailing_space(self):
        _, sugg = self.cs.completions("")
        by_text = {s["text"] for s in sugg}
        self.assertIn("hello ", by_text)   # syntax "hello [name]"
        self.assertIn("help", by_text)     # syntax "help", no arg

    def test_prefix_filters_names_and_aliases(self):
        _, sugg = self.cs.completions("hel")
        self.assertEqual([s["text"] for s in sugg], ["hello ", "help"])
        _, sugg = self.cs.completions("gre")   # alias greet
        self.assertEqual([s["text"] for s in sugg], ["hello "])

    def test_after_space_delegates_to_complete(self):
        title, sugg = self.cs.completions("hello ")
        self.assertEqual(title, "Names")
        self.assertEqual([s["label"] for s in sugg], ["ana", "bob", "cara"])
        self.assertEqual(sugg[1]["text"], "hello bob")
        self.assertTrue(all(s["kind"] == "arg" for s in sugg))

    def test_arg_is_stripped_before_delegation(self):
        _, sugg = self.cs.completions("hello  bo")
        self.assertEqual([s["label"] for s in sugg], ["bob"])

    def test_syntax_fallback_row_when_no_provider(self):
        title, sugg = self.cs.completions("help ")
        self.assertEqual(title, "help")
        self.assertEqual(sugg, [{"text": "help ", "label": ":help",
                                 "hint": "keys & commands", "kind": "info"}])

    def test_unknown_command_with_arg(self):
        self.assertEqual(self.cs.completions("zz x"), ("?", []))


class TestRun(unittest.TestCase):
    def setUp(self):
        self.cs, self.log = make_commands()

    def test_dispatch_with_arg(self):
        self.assertEqual(self.cs.run(":hello world"), "hello world")
        self.assertEqual(self.log, [("hello", "world")])

    def test_dispatch_without_arg(self):
        self.assertEqual(self.cs.run("hello"), "hello")
        self.assertEqual(self.log, [("hello", "")])

    def test_whitespace_collapses(self):
        self.cs.run("  :hello   a   b ")
        self.assertEqual(self.log, [("hello", "a b")])

    def test_alias_dispatch_case_insensitive(self):
        self.cs.run("HI x")
        self.assertEqual(self.log, [("hello", "x")])

    def test_unique_prefix_dispatch(self):
        self.cs.run("qu")
        self.assertEqual(self.log, [("quit", "")])

    def test_unknown(self):
        self.assertEqual(self.cs.run(":ZZ now"), "unknown: zz  (try :help)")
        self.assertEqual(self.log, [])

    def test_empty(self):
        self.assertEqual(self.cs.run(""), "")
        self.assertEqual(self.cs.run(":"), "")
        self.assertEqual(self.cs.run("   "), "")
        self.assertEqual(self.log, [])

    def test_help_rows(self):
        self.assertEqual(self.cs.help_rows()[0], (":hello [name]", "say hello"))
        self.assertEqual(len(self.cs.help_rows()), 4)


class TestPaletteKeys(unittest.TestCase):
    def setUp(self):
        self.cs, self.log = make_commands()
        self.statuses = []
        self.pal = Palette(self.cs, on_status=self.statuses.append)
        self.app = FakeApp()

    def type_(self, text):
        for ch in text:
            self.app.capture(ch)

    def test_open_grabs_capture_and_clears(self):
        self.pal.edit.buf = "junk"
        self.pal.sel = 3
        self.pal.open_(self.app)
        self.assertTrue(self.pal.open)
        self.assertIsNotNone(self.app.capture)
        self.assertEqual(self.pal.edit.buf, "")
        self.assertEqual(self.pal.sel, 0)

    def test_every_key_is_consumed(self):
        self.pal.open_(self.app)
        for key in ("a", Key.TAB, Key.UP, Key.DOWN, Key.LEFT, Key.PGUP, "F?"):
            self.assertTrue(self.app.capture(key))

    def test_typing_feeds_the_line_edit(self):
        self.pal.open_(self.app)
        self.type_("hel")
        self.assertEqual(self.pal.edit.buf, "hel")
        self.assertEqual(self.pal.edit.cursor, 3)

    def test_tab_accepts_highlighted_suggestion(self):
        self.pal.open_(self.app)
        self.type_("hel")
        self.app.capture(Key.TAB)
        self.assertEqual(self.pal.edit.buf, "hello ")   # first suggestion
        self.assertEqual(self.pal.edit.cursor, 6)
        self.assertEqual(self.pal.sel, 0)

    def test_tab_after_arrow_takes_the_selected_arg(self):
        self.pal.open_(self.app)
        self.type_("hello ")
        self.app.capture(Key.DOWN)
        self.assertEqual(self.pal.sel, 1)
        self.app.capture(Key.TAB)
        self.assertEqual(self.pal.edit.buf, "hello bob")

    def test_tab_with_no_suggestions_is_a_no_op(self):
        self.pal.open_(self.app)
        self.type_("zz x")
        self.app.capture(Key.TAB)
        self.assertEqual(self.pal.edit.buf, "zz x")

    def test_arrow_selection_wraps(self):
        self.pal.open_(self.app)          # 4 command suggestions
        self.app.capture(Key.UP)
        self.assertEqual(self.pal.sel, 3)
        self.app.capture(Key.DOWN)
        self.assertEqual(self.pal.sel, 0)
        self.app.capture(Key.SHIFT_TAB)   # same as UP
        self.assertEqual(self.pal.sel, 3)
        self.app.capture(Key.DOWN)
        self.app.capture(Key.DOWN)
        self.assertEqual(self.pal.sel, 1)

    def test_buffer_change_resets_selection(self):
        self.pal.open_(self.app)
        self.app.capture(Key.DOWN)
        self.app.capture(Key.DOWN)
        self.assertEqual(self.pal.sel, 2)
        self.app.capture("h")
        self.assertEqual(self.pal.sel, 0)
        self.app.capture(Key.DOWN)
        self.assertEqual(self.pal.sel, 1)
        self.app.capture(Key.BACKSPACE)
        self.assertEqual(self.pal.sel, 0)

    def test_non_editing_key_keeps_selection(self):
        self.pal.open_(self.app)
        self.app.capture(Key.DOWN)
        self.app.capture(Key.LEFT)        # cursor move, no buffer change
        self.assertEqual(self.pal.sel, 1)

    def test_line_edit_cursor_editing(self):
        self.pal.open_(self.app)
        self.type_("ab")
        self.app.capture(Key.LEFT)
        self.app.capture("c")
        self.assertEqual(self.pal.edit.buf, "acb")

    def test_enter_runs_closes_and_reports_status(self):
        self.pal.open_(self.app)
        self.type_("hello bob")
        self.app.capture(Key.ENTER)
        self.assertEqual(self.log, [("hello", "bob")])
        self.assertEqual(self.statuses, ["hello bob"])
        self.assertFalse(self.pal.open)
        self.assertIsNone(self.app.capture)
        self.assertEqual(self.pal.edit.buf, "")
        self.assertEqual(self.pal.sel, 0)

    def test_enter_with_empty_status_skips_the_callback(self):
        self.pal.open_(self.app)
        self.type_("quit")
        self.app.capture(Key.ENTER)
        self.assertEqual(self.log, [("quit", "")])
        self.assertEqual(self.statuses, [])
        self.assertFalse(self.pal.open)

    def test_enter_unknown_reports_the_error(self):
        self.pal.open_(self.app)
        self.type_("zz")
        self.app.capture(Key.ENTER)
        self.assertEqual(self.statuses, ["unknown: zz  (try :help)"])

    def test_enter_empty_buffer_just_closes(self):
        self.pal.open_(self.app)
        self.app.capture(Key.ENTER)
        self.assertEqual(self.statuses, [])
        self.assertFalse(self.pal.open)
        self.assertIsNone(self.app.capture)

    def test_esc_cancels_without_running(self):
        self.pal.open_(self.app)
        self.type_("hello bob")
        self.app.capture(Key.ESC)
        self.assertEqual(self.log, [])
        self.assertEqual(self.statuses, [])
        self.assertFalse(self.pal.open)
        self.assertIsNone(self.app.capture)
        self.assertEqual(self.pal.edit.buf, "")

    def test_close_leaves_foreign_capture_alone(self):
        self.pal.open_(self.app)
        other = lambda key: True
        self.app.capture = other
        self.pal.close(self.app)
        self.assertIs(self.app.capture, other)

    def test_reopen_round_trip(self):
        self.pal.open_(self.app)
        self.type_("hel")
        self.app.capture(Key.ESC)
        self.pal.open_(self.app)
        self.assertEqual(self.pal.edit.buf, "")
        self.type_("help")
        self.app.capture(Key.ENTER)
        self.assertEqual(self.statuses, ["help"])


class OtherTheme(Theme):
    white = (10, 20, 30)
    accent = (11, 22, 33)
    accent2 = (44, 55, 66)
    highlight = (77, 88, 99)


class TestDrawPaletteBar(unittest.TestCase):
    def setUp(self):
        self.cs, _ = make_commands()
        self.pal = Palette(self.cs)
        self._depth = term.get_color_depth()
        term.set_color_depth("truecolor")

    def tearDown(self):
        term.set_color_depth(self._depth)

    def draw(self, buf, theme=Theme, cursor=None, w=60):
        self.pal.edit.buf = buf
        self.pal.edit.cursor = len(buf) if cursor is None else cursor
        cv = Canvas(w, 1)
        draw_palette_bar(cv.region(), self.pal, theme=theme)
        return cv

    def test_prompt_cursor_and_ghost(self):
        cv = self.draw("hel")
        text = render_plain(cv)
        self.assertIn(":hel", text)
        self.assertIn("█", text)
        self.assertIn("lo", text)          # ghost of "hello "
        self.assertIn("⇥ tab", text)

    def test_no_ghost_when_suggestion_does_not_extend_buffer(self):
        cv = self.draw("zz x")
        text = render_plain(cv)
        self.assertIn(":zz x", text)
        self.assertNotIn("⇥ tab", text)

    def test_mid_buffer_cursor_renders(self):
        cv = self.draw("help", cursor=2)
        text = render_plain(cv)
        self.assertIn(":help", text)
        self.assertNotIn("█", text)        # reversed char instead

    def test_theme_parameterized(self):
        base = self.draw("hel").to_lines()
        again = self.draw("hel").to_lines()
        other = self.draw("hel", theme=OtherTheme).to_lines()
        self.assertEqual(base, again)
        self.assertNotEqual(base, other)


class TestDrawPaletteMenu(unittest.TestCase):
    def setUp(self):
        self.cs, _ = make_commands()
        self.pal = Palette(self.cs)
        self._depth = term.get_color_depth()
        term.set_color_depth("truecolor")

    def tearDown(self):
        term.set_color_depth(self._depth)

    def draw(self, buf, sel=0, theme=Theme, w=80, h=14, cs=None, hits=None):
        pal = Palette(cs if cs is not None else self.cs)
        pal.edit.buf = buf
        pal.edit.cursor = len(buf)
        pal.sel = sel
        cv = Canvas(w, h)
        draw_palette_menu(cv.region(hits=hits), pal, theme=theme)
        return cv, pal

    def test_renders_title_labels_and_hints(self):
        cv, _ = self.draw("")
        text = render_plain(cv)
        self.assertIn("Commands", text)
        self.assertIn(":hello [name]", text)
        self.assertIn("say hello", text)
        self.assertIn("▸", text)           # selection marker

    def test_arg_menu(self):
        cv, _ = self.draw("hello ")
        text = render_plain(cv)
        self.assertIn("Names", text)
        self.assertIn("bob", text)
        self.assertIn("--bob", text)

    def test_selection_is_clamped(self):
        _, pal = self.draw("", sel=99)
        self.assertEqual(pal.sel, 3)

    def test_empty_suggestions_draw_nothing(self):
        hits = HitMap()
        cv, _ = self.draw("zz x", hits=hits)
        self.assertEqual(render_plain(cv).strip(), "")
        self.assertEqual(len(hits), 0)

    def test_click_swallowing_hit_over_the_box(self):
        hits = HitMap()
        cv, _ = self.draw("", hits=hits)
        self.assertEqual(len(hits), 1)
        # rows: status_row = 12, h = 4 + 2 -> box rows 6..11, cols 1..w
        action = hits.lookup(7, 3)
        self.assertTrue(callable(action))
        self.assertIsNone(action())
        self.assertIsNone(hits.lookup(0, 0))

    def test_overflow_counter_and_window(self):
        specs = [{"name": f"cmd{i}", "aliases": [], "syntax": f"cmd{i}",
                  "desc": f"desc {i}", "run": lambda a: "", "complete": None}
                 for i in range(8)]
        cs = CommandSet(specs)
        # h=10: status_row=8, maxshow=min(8, 4, 10)=4
        cv, _ = self.draw("", cs=cs, h=10)
        text = render_plain(cv)
        self.assertIn("1/8", text)
        self.assertIn("cmd0", text)
        self.assertNotIn("cmd7", text)
        cv, _ = self.draw("", cs=cs, h=10, sel=6)
        text = render_plain(cv)
        self.assertIn("7/8", text)         # window follows the selection
        self.assertIn("cmd6", text)
        self.assertNotIn("cmd0", text)

    def test_theme_parameterized(self):
        base = self.draw("")[0].to_lines()
        other = self.draw("", theme=OtherTheme)[0].to_lines()
        self.assertNotEqual(base, other)


class TestWorldCupSpecs(unittest.TestCase):
    """The World Cup command specs (state.command_specs) stay consumable
    by CommandSet. Since the app's palette drawing now IS the kit's, the
    byte gate lives in the palette-open view golden; this guards the
    spec contract the golden rides on."""

    def _specs(self):
        import state as S
        return S.command_specs(S.AppState(), None, None)

    def test_specs_have_the_kit_fields(self):
        for c in self._specs():
            for field in ("name", "aliases", "syntax", "desc",
                          "run", "complete"):
                self.assertIn(field, c, c.get("name"))
            self.assertTrue(callable(c["run"]), c["name"])

    def test_arg_commands_are_marked_by_syntax_space(self):
        # the kit derives "takes an argument" from a space in the syntax
        args = {c["name"]: " " in c["syntax"] for c in self._specs()}
        self.assertTrue(args["schedule"])
        self.assertTrue(args["team"])
        self.assertFalse(args["bracket"])
        self.assertFalse(args["quit"])

    def test_menu_completion_matches_the_palette_golden(self):
        # the palette-open golden types "gr": one suggestion, ':groups'
        cs = CommandSet(self._specs())
        title, sugg = cs.completions("gr")
        self.assertEqual(title, "Commands")
        self.assertEqual([s["text"] for s in sugg], ["groups "])
        self.assertEqual(sugg[0]["label"], ":groups [A-L]")


if __name__ == "__main__":
    unittest.main()
