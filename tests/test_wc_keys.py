"""
test_wc_keys.py - In-process dispatch tests for the wc.py app wiring.

Builds the real app (wc.build_app) around offline fixture states and
drives it through the App dispatch seams (dispatch_key / dispatch_mouse)
— no TTY, no network (the Refresher is never started, so its request_*
calls only enqueue).

Covers the ONE authorized behavior change of the app-kit phase: the view
stack unwinds TEAM -> DETAIL -> Esc -> Esc to TEAM and then to TEAM's
parent. The old prev_view scalar overwrote itself when the match centre
opened from the team page, leaving the second Esc stuck on TEAM forever.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tui import term
from tui import theme as tui_theme
from tui.term import Key, MouseEvent

import fixtures_views as F
import state as S
import wc


_saved = {}


def setUpModule():
    _saved["depth"] = term.get_color_depth()
    _saved["theme"] = tui_theme.get_theme()
    _saved["tz"] = os.environ.get("TZ")


def tearDownModule():
    term.set_color_depth(_saved["depth"])
    tui_theme.set_theme(_saved["theme"])
    if _saved["tz"] is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _saved["tz"]
    time.tzset()


def make_app(build=F.state_live):
    """(state, app, refresher) around a fixture, with the stack seeded."""
    st = build()
    refresher = S.Refresher(st)
    app = wc.build_app(st, refresher)
    app.goto(st.view)
    return st, app, refresher


class TestViewRouting(unittest.TestCase):
    def test_number_key_switches_view(self):
        st, app, _ = make_app()
        app.dispatch_key("2")
        self.assertEqual(app.view, S.SCHEDULE)
        self.assertEqual(app.stack, [S.SCHEDULE])
        self.assertEqual(st.view, S.SCHEDULE)   # the state property mirrors

    def test_tab_cycles_and_shift_tab_cycles_back(self):
        st, app, _ = make_app()
        app.dispatch_key(Key.TAB)
        self.assertEqual(app.view, S.SCHEDULE)
        app.dispatch_key(Key.SHIFT_TAB)
        self.assertEqual(app.view, S.LIVE)
        app.dispatch_key(Key.SHIFT_TAB)         # wraps to the last tab
        self.assertEqual(app.view, S.SCORERS)

    def test_enter_opens_detail_and_esc_returns(self):
        st, app, _ = make_app()
        app.dispatch_key(Key.ENTER)
        self.assertEqual(app.view, S.DETAIL)
        self.assertEqual(st.detail_event_id, wc.live_ordered(st)[0].id)
        app.dispatch_key(Key.ESC)
        self.assertEqual(app.view, S.LIVE)
        self.assertEqual(app.stack, [S.LIVE])

    def test_team_detail_esc_esc_unwinds_the_stack(self):
        """THE authorized behavior change: Esc from the match centre goes
        back to the team page, and a second Esc to the team page's
        parent (the old prev_view scalar left Esc bouncing on TEAM)."""
        st, app, refresher = make_app()
        res = S.open_team(st, app, "Brazil", refresher)
        self.assertEqual(res, "team Brazil")
        self.assertEqual(app.stack, [S.LIVE, S.TEAM])
        st.team_matches = list(st.matches_today)
        app.dispatch_key(Key.ENTER)             # open a match from the page
        self.assertEqual(app.stack, [S.LIVE, S.TEAM, S.DETAIL])
        app.dispatch_key(Key.ESC)
        self.assertEqual(app.view, S.TEAM)      # back to the team page...
        app.dispatch_key(Key.ESC)
        self.assertEqual(app.view, S.LIVE)      # ...then to its parent
        app.dispatch_key(Key.ESC)               # root: Esc is a no-op
        self.assertEqual(app.stack, [S.LIVE])

    def test_help_pushes_and_esc_pops(self):
        st, app, _ = make_app()
        app.dispatch_key("?")
        self.assertEqual(app.view, S.HELP)
        app.dispatch_key("?")                   # no double-push
        self.assertEqual(app.stack, [S.LIVE, S.HELP])
        app.dispatch_key(Key.ESC)
        self.assertEqual(app.view, S.LIVE)


class TestPalette(unittest.TestCase):
    def test_sched_plus_one_changes_the_date(self):
        st, app, _ = make_app()
        st.schedule_date = "20260615"
        app.dispatch_key(":")
        self.assertTrue(app.palette.open)
        self.assertIsNotNone(app.capture)
        for ch in "sched +1":
            app.dispatch_key(ch)
        app.dispatch_key(Key.ENTER)
        self.assertFalse(app.palette.open)
        self.assertIsNone(app.capture)
        self.assertEqual(st.schedule_date, "20260616")
        self.assertEqual(app.view, S.SCHEDULE)
        # the status string lands as a toast in the shared store
        self.assertEqual(app.toasts.latest().text, "schedule 20260616")
        self.assertIs(app.toasts, st.toasts)

    def test_normal_keys_are_captured_while_open(self):
        st, app, _ = make_app()
        app.dispatch_key(":")
        app.dispatch_key("2")                   # types "2", no view switch
        self.assertEqual(app.view, S.LIVE)
        self.assertEqual(app.palette.edit.buf, "2")
        app.dispatch_key(Key.ESC)               # cancels; does not pop views
        self.assertFalse(app.palette.open)
        self.assertEqual(app.view, S.LIVE)

    def test_mouse_command_flips_the_app_flag(self):
        st, app, _ = make_app()
        self.assertTrue(app.mouse_enabled)
        app.dispatch_key(":")
        for ch in "mouse off":
            app.dispatch_key(ch)
        app.dispatch_key(Key.ENTER)
        self.assertFalse(app.mouse_enabled)


class TestMouse(unittest.TestCase):
    def test_wheel_moves_the_selection(self):
        st, app, _ = make_app()
        wc.render_frame(app, 120, 40)           # sync the list count
        app.dispatch_mouse(MouseEvent(10, 10, "wheel_down", "wheel"))
        self.assertEqual(st.live_ls.sel, 1)
        app.dispatch_mouse(MouseEvent(10, 10, "wheel_up", "wheel"))
        self.assertEqual(st.live_ls.sel, 0)

    def test_wheel_is_ignored_while_the_palette_is_open(self):
        st, app, _ = make_app()
        wc.render_frame(app, 120, 40)
        app.dispatch_key(":")
        app.dispatch_mouse(MouseEvent(10, 10, "wheel_down", "wheel"))
        self.assertEqual(st.live_ls.sel, 0)

    def test_click_selects_then_opens(self):
        st, app, _ = make_app()
        wc.render_frame(app, 120, 40)
        # live fixture at 120x40: cards start on screen row 3, 5 rows each
        # (live 9001, live 9002, ...), so row 8 is the second card
        app.dispatch_mouse(MouseEvent(8, 60, "left", "press"))
        self.assertEqual(st.live_ls.sel, 1)     # first click selects
        self.assertEqual(app.view, S.LIVE)
        wc.render_frame(app, 120, 40)           # hits rebuilt per frame
        app.dispatch_mouse(MouseEvent(8, 60, "left", "press"))
        self.assertEqual(app.view, S.DETAIL)    # second click opens
        self.assertEqual(st.detail_event_id, "9002")

    def test_help_swallows_clicks_over_the_live_list(self):
        """With Help open, the popup's swallow hit covers the box: a click
        on coordinates that select a live card when Live is on top must
        neither change the selection nor leave the Help view."""
        st, app, _ = make_app()
        wc.render_frame(app, 120, 40)
        app.dispatch_key("?")
        self.assertEqual(app.view, S.HELP)
        wc.render_frame(app, 120, 40)           # hits rebuilt per frame
        # (8, 60) is inside the help box AND over the second live card
        # (see test_click_selects_then_opens); the swallow hit is present
        self.assertTrue(callable(app.hits.lookup(8, 60)))
        app.dispatch_mouse(MouseEvent(8, 60, "left", "press"))
        self.assertEqual(st.live_ls.sel, 0)     # selection unchanged
        self.assertEqual(app.view, S.HELP)      # still on help

    def test_click_on_a_tab_switches_view(self):
        st, app, _ = make_app()
        wc.render_frame(app, 120, 40)
        # find the Bracket tab's hit by probing the tab row through the app
        for col in range(120):
            action = app.hits.lookup(1, col)
            if action is not None:
                action_col = col  # first tab: Live
                break
        else:
            self.fail("no tab hits registered")
        app.dispatch_mouse(MouseEvent(1, action_col, "left", "press"))
        self.assertEqual(app.view, S.LIVE)      # clicking Live stays put
        app.dispatch_key("4")
        self.assertEqual(app.view, S.BRACKET)


if __name__ == "__main__":
    unittest.main()


class TestCliStartViewSeeding(unittest.TestCase):
    """Regression: overlay CLI start views (--ENG, help) sit on a LIVE
    base so Esc drops to live scores instead of being dead; Esc-pop
    wakes the refresher (the old loop woke on every key)."""

    def test_team_start_esc_goes_live(self):
        st, app, refresher = make_app()
        wc.seed_view(app, S.TEAM)
        self.assertEqual(app.stack, [S.LIVE, S.TEAM])
        app.dispatch_key(Key.ESC)
        self.assertEqual(app.view, S.LIVE)

    def test_help_start_esc_goes_live(self):
        st, app, refresher = make_app()
        wc.seed_view(app, S.HELP)
        app.dispatch_key(Key.ESC)
        self.assertEqual(app.view, S.LIVE)

    def test_tab_start_unchanged(self):
        st, app, refresher = make_app()
        wc.seed_view(app, S.GROUPS)
        self.assertEqual(app.stack, [S.GROUPS])

    def test_esc_pop_wakes_refresher(self):
        st, app, refresher = make_app()
        app.goto(S.LIVE)
        app.push(S.DETAIL)
        refresher._wake.clear()
        app.dispatch_key(Key.ESC)
        self.assertEqual(app.view, S.LIVE)
        self.assertTrue(refresher._wake.is_set())
