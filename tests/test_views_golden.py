"""
test_views_golden.py - Byte-identity oracle for every World Cup view.

Renders each offline fixture (tests/fixtures_views.py) at 120x40 and 80x24,
masks the wall clock (the ONE volatile fragment), and compares the full-ANSI
frame byte-for-byte against tests/goldens/<view>_<w>x<h>.txt.

    GENERATE_GOLDENS=1 python3 -m unittest tests.test_views_golden

writes the goldens instead of comparing. Goldens are captured from the
pre-Region tree and must NEVER be regenerated to make a failure pass: a
golden failure means the rendering change is wrong.
"""

import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tui import term
from tui import theme as tui_theme
from tui.testing import first_diff, mask_text

import fixtures_views as F
import wc


GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goldens")
SIZES = [(120, 40), (80, 24)]
CLOCK_MASK = [(re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}"), "HH:MM:SS")]
GENERATE = os.environ.get("GENERATE_GOLDENS") == "1"

FIXTURES = [
    ("live", F.state_live),
    ("live_palette", F.state_live_palette),
    ("schedule", F.state_schedule),
    ("groups", F.state_groups),
    ("bracket", F.state_bracket),
    ("bracket_scrolled", F.state_bracket_scrolled),
    ("scorers_goals", F.state_scorers_goals),
    ("scorers_assists", F.state_scorers_assists),
    ("detail_lineups", F.state_detail_lineups),
    ("detail_timeline", F.state_detail_timeline),
    ("detail_stats", F.state_detail_stats),
    ("detail_odds", F.state_detail_odds),
    ("team", F.state_team),
    ("help", F.state_help),
]

# Phase W: empty / loading / edge states found golden-blind by the Phase R
# fidelity review. Captured at 120x40 only, except where the 80x24 layout
# differs meaningfully (noted per fixture) — those carry both sizes.
BOTH = SIZES
ONE = [(120, 40)]
EDGE_FIXTURES = [
    ("live_empty", F.state_live_empty, ONE),
    ("live_toast_flash", F.state_live_toast_flash, ONE),
    ("live_toast_error", F.state_live_toast_error, ONE),
    ("live_toast_info", F.state_live_toast_info, ONE),
    ("live_reconnecting", F.state_live_reconnecting, ONE),
    ("schedule_loading", F.state_schedule_loading, ONE),
    ("groups_loading", F.state_groups_loading, ONE),
    ("groups_scrolled", F.state_groups_scrolled, BOTH),    # 2 cols vs 1 col
    ("bracket_loading", F.state_bracket_loading, ONE),
    ("bracket_empty", F.state_bracket_empty, BOTH),        # viewport clip differs
    ("scorers_loading", F.state_scorers_loading, ONE),
    ("detail_loading_unknown", F.state_detail_loading_unknown, ONE),
    ("detail_empty_lineups", F.state_detail_empty_lineups, ONE),
    ("detail_empty_timeline", F.state_detail_empty_timeline, ONE),
    ("detail_empty_stats", F.state_detail_empty_stats, ONE),
    ("detail_lineups_fallback", F.state_detail_lineups_fallback, BOTH),  # pitch geometry
    ("detail_timeline_scrolled", F.state_detail_timeline_scrolled, BOTH),  # window size
    ("detail_odds_decimal", F.state_detail_odds_decimal, ONE),
    ("team_loading", F.state_team_loading, ONE),
]

ALL_FIXTURES = [(n, b, SIZES) for n, b in FIXTURES] + EDGE_FIXTURES

_saved = {}


def setUpModule():
    _saved["depth"] = term.get_color_depth()
    _saved["theme"] = tui_theme.get_theme()
    _saved["tz"] = os.environ.get("TZ")
    _saved["odds_fmt"] = os.environ.get("WCUP_ODDS_FORMAT")


def tearDownModule():
    term.set_color_depth(_saved["depth"])
    tui_theme.set_theme(_saved["theme"])
    if _saved["tz"] is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _saved["tz"]
    time.tzset()
    if _saved["odds_fmt"] is None:
        os.environ.pop("WCUP_ODDS_FORMAT", None)
    else:
        os.environ["WCUP_ODDS_FORMAT"] = _saved["odds_fmt"]


def render_frame(build, cols, rows):
    """One masked full-ANSI frame from a fresh fixture state, rendered
    through the real wc app wiring (build_app + render_frame)."""
    app = F.make_app(build)
    lines = wc.render_frame(app, cols, rows)
    return mask_text("\n".join(lines), CLOCK_MASK)


def golden_path(name, cols, rows):
    return os.path.join(GOLDEN_DIR, "%s_%dx%d.txt" % (name, cols, rows))


class TestViewGoldens(unittest.TestCase):
    def test_frames_match_goldens(self):
        for name, build, sizes in ALL_FIXTURES:
            for cols, rows in sizes:
                with self.subTest(view=name, size="%dx%d" % (cols, rows)):
                    frame = render_frame(build, cols, rows)
                    path = golden_path(name, cols, rows)
                    if GENERATE:
                        os.makedirs(GOLDEN_DIR, exist_ok=True)
                        with open(path, "w") as f:
                            f.write(frame)
                        continue
                    self.assertTrue(
                        os.path.exists(path),
                        "missing golden %s (capture with GENERATE_GOLDENS=1)"
                        % path)
                    with open(path) as f:
                        want = f.read()
                    if frame != want:
                        diff = first_diff(want, frame)
                        self.fail(
                            "%s @ %dx%d differs from golden at line %d\n"
                            " golden: %r\n actual: %r"
                            % (name, cols, rows, diff[0], diff[1], diff[2]))

    def test_render_is_deterministic_in_process(self):
        """Two renders from fresh fixture states are byte-identical."""
        for name, build, _sizes in ALL_FIXTURES:
            with self.subTest(view=name):
                a = render_frame(build, 120, 40)
                b = render_frame(build, 120, 40)
                self.assertEqual(a, b, "nondeterministic frame: " + name)


if __name__ == "__main__":
    unittest.main()
