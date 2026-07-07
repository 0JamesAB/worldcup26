#!/usr/bin/env python3
"""
wc.py - World Cup 2026 terminal dashboard. CLI entry point + app wiring.

Usage:
    python3 wc.py                 # launch the live dashboard
    python3 wc.py groups          # start on a given view (live/schedule/groups/bracket/scorers)
    python3 wc.py --date 20260703 # start on the schedule for a date
    python3 wc.py --snapshot 120x40 [view]   # render one frame to stdout and exit (no TTY)

Keys:  1-5 views · Tab cycle · ↑↓ move · ←→ day/tabs/scroll · Enter open
       : command line · r refresh · ? help · q quit
"""

import sys
from datetime import datetime, timezone

FAR = datetime.max.replace(tzinfo=timezone.utc)

from tui import term
from tui.app import App
from tui.canvas import Canvas
from tui.commands import CommandSet, Palette
from tui.term import Key
from tui.theme import set_theme
from palette import WorldCupTheme
set_theme(WorldCupTheme)

import espn
import state as S
import views


def live_ordered(st):
    order = {"in": 0, "pre": 1, "post": 2}
    return sorted(st.matches_today,
                  key=lambda m: (order.get(m.state, 3), m.date or FAR))


# ----------------------------------------------------------------------------
# app wiring — the whole input surface lives here, on the tui App kit
# ----------------------------------------------------------------------------

def build_app(st, refresher):
    """Wire the World Cup app: eight views with their keymaps, the global
    bindings, the ':' palette, and the state hooks views.py's mouse-hit
    closures call. Routing (view stack, capture, dispatch) is the kit's."""
    app = App(state=st, fps=8, tick=0.33, mouse=True, lock=st.lock)
    st.app = app             # st.view / st.dirty now read through the app
    app.toasts = st.toasts   # one shared toast store (kit prunes, app draws)

    def goto(view):
        app.goto(view)
        refresher.wake()     # fetch the new view's data promptly

    def cycle(direction):
        cur = app.view
        if cur not in S.TAB_VIEWS:   # detail/help/team: cycle from the tab below
            cur = next((v for v in reversed(app.stack) if v in S.TAB_VIEWS),
                       S.TAB_VIEWS[0])
        i = S.TAB_VIEWS.index(cur)
        goto(S.TAB_VIEWS[(i + direction) % len(S.TAB_VIEWS)])

    def open_match(event_id):
        """Jump to the match centre for an event id (Esc returns)."""
        st.detail_event_id = event_id
        st.detail_tab = 0
        st.detail_ss.home()
        if app.view != S.DETAIL:
            app.push(S.DETAIL)
        refresher.request_summary(event_id)

    def open_help():
        if app.view != S.HELP:
            app.push(S.HELP)

    def refresh_now():
        refresher.force_all()
        app.toast("refreshing…", "info", 3)

    def shift_day(delta):
        d = S.resolve_date(("+" if delta > 0 else "-") + "1", st.schedule_date)
        if d:
            st.schedule_date = d
            st.sched_ls.sel = 0
            refresher.request_schedule(d)

    def scorers_tab(delta):
        st.scorers_tab = (st.scorers_tab + delta) % 2
        st.scorers_ls.sel = 0

    def detail_tab(delta):
        st.detail_tab = (st.detail_tab + delta) % len(views.DETAIL_TABS)
        st.detail_ss.home()

    # Scroll keymaps feed the ScrollStates; each view's render keeps the
    # extents current via set_extent, so scroll() clamps at both ends.
    def detail_scroll(d):
        st.detail_ss.scroll(1 if d > 0 else -1)

    def groups_scroll(d):
        st.groups_ss.scroll(1 if d > 0 else -1)

    def bracket_v(d):
        st.bracket_ss_y.scroll(d * 2)

    def bracket_h(d):
        st.bracket_ss_x.scroll(d * 6)

    def open_from(ls, items):
        """Enter action for a list view: open its selected match."""
        def go():
            lst = items()
            if lst:
                open_match(lst[max(0, min(ls.sel, len(lst) - 1))].id)
        return go

    def sel_nav(ls, extra=None):
        """The standard cursor keymap over a ListState."""
        keys = {(Key.UP, "k"): lambda: ls.move(-1),
                (Key.DOWN, "j"): lambda: ls.move(1),
                Key.PGUP: lambda: ls.move(-5), Key.PGDN: lambda: ls.move(5),
                Key.HOME: ls.home, Key.END: ls.end}
        keys.update(extra or {})
        return keys

    def vert_nav(fn, pg=1, ends=1):
        """Scroll-view keymap: vertical keys feed `fn` with a signed step."""
        return {(Key.UP, "k"): lambda: fn(-1), (Key.DOWN, "j"): lambda: fn(1),
                Key.PGUP: lambda: fn(-pg), Key.PGDN: lambda: fn(pg),
                Key.HOME: lambda: fn(-ends), Key.END: lambda: fn(ends)}

    def horiz_nav(fn):
        return {(Key.LEFT, "h"): lambda: fn(-1), (Key.RIGHT, "l"): lambda: fn(1)}

    def wheel(fn):
        """Wheel = one vertical step. (The kit drops all mouse input
        while a capture is active, so no palette guard is needed here.)"""
        return fn

    sched_keys = horiz_nav(shift_day)
    sched_keys[Key.ENTER] = open_from(st.sched_ls, lambda: st.schedule_matches)
    bracket_keys = vert_nav(bracket_v, pg=5, ends=9999)
    bracket_keys.update(horiz_nav(bracket_h))
    detail_keys = vert_nav(detail_scroll)
    detail_keys.update(horiz_nav(detail_tab))

    app.add_view(S.LIVE, views.view_live,
                 keys=sel_nav(st.live_ls, {Key.ENTER: open_from(
                     st.live_ls, lambda: live_ordered(st))}),
                 on_wheel=wheel(st.live_ls.move))
    app.add_view(S.SCHEDULE, views.view_schedule,
                 keys=sel_nav(st.sched_ls, sched_keys),
                 on_wheel=wheel(st.sched_ls.move))
    app.add_view(S.GROUPS, views.view_groups, keys=vert_nav(groups_scroll),
                 on_wheel=wheel(groups_scroll))
    app.add_view(S.BRACKET, views.view_bracket, keys=bracket_keys,
                 on_wheel=wheel(bracket_v))
    app.add_view(S.SCORERS, views.view_scorers,
                 keys=sel_nav(st.scorers_ls, horiz_nav(scorers_tab)),
                 on_wheel=wheel(st.scorers_ls.move))
    app.add_view(S.DETAIL, views.view_detail, keys=detail_keys,
                 on_wheel=wheel(detail_scroll))
    app.add_view(S.TEAM, views.view_team,
                 keys=sel_nav(st.sched_ls, {Key.ENTER: open_from(
                     st.sched_ls, lambda: getattr(st, "team_matches", []))}),
                 on_wheel=wheel(st.sched_ls.move))
    app.add_view(S.HELP, views.view_help, on_wheel=lambda d: None)

    pal = Palette(CommandSet(S.command_specs(st, app, refresher)),
                  on_status=lambda msg: app.toast(msg, "info", 4))
    app.palette = pal

    def back():
        """Esc: pop the view stack and wake the refresher so the view
        underneath refreshes promptly (the old loop woke on every key)."""
        app.pop()
        refresher.wake()

    binds = {("q", "Q"): app.quit,
             (":", "/"): lambda: pal.open_(app),
             "?": open_help,
             ("r", "R"): refresh_now,
             Key.ESC: back,
             Key.TAB: lambda: cycle(1),
             Key.SHIFT_TAB: lambda: cycle(-1)}
    for i, v in enumerate(S.TAB_VIEWS):
        binds[str(i + 1)] = lambda v=v: goto(v)
    app.bind(binds)

    # hooks for views.py's click closures
    st.open_match = open_match
    st.change_view = goto
    st.sched_day = shift_day
    return app


def render_frame(app, cols, rows):
    """One full frame (list of ANSI lines) without entering the terminal —
    exactly what App.run paints; used by --snapshot and the golden tests."""
    with app.lock:
        app.frame += 1
        app.hits.clear()
        cv = Canvas(cols, rows, views.base())
        views.draw_frame(cv.region(hits=app.hits), app)
        return cv.to_lines()


def seed_view(app, view):
    """Seed the view stack for a CLI start view. Overlay views (team,
    help, detail) sit on a LIVE base so Esc drops to live scores,
    matching the pre-kit prev_view behavior."""
    if view in (S.TEAM, S.HELP, S.DETAIL):
        app.goto(S.LIVE)
        app.push(view)
    else:
        app.goto(view)


def initial_load(st, refresher):
    st.status = "connecting to ESPN…"
    try:
        espn.fetch_team_colors()
    except Exception:
        pass
    try:
        refresher._do_today(force=True)
    except Exception as e:
        st.status = f"startup error: {e}"


USAGE = """\
wcup — FIFA World Cup 2026 terminal dashboard

  wcup                 live scores (today)
  wcup --ENG           open a nation's page (any 3-letter code: BRA, USA, MEX…)
  wcup --team england  same, by name
  wcup groups          start on a view: live | schedule | groups | bracket | scorers
  wcup --date 20260703 schedule for a date (YYYYMMDD)
  wcup --teams         list every team code
  wcup --snapshot WxH [view|--ABBR]   render one frame and exit (no TTY)
  wcup --help          this help

In-app:  1-5 views · ↑↓ move · ←→ day/tabs · Enter open · : command · ? help · q quit

Odds:  win-probability odds (from ESPN's public feed, no key needed) show on
  upcoming-match cards and in the match centre. Set WCUP_ODDS=off to hide them,
  or WCUP_ODDS_FORMAT=decimal for decimal instead of American prices.
"""


def parse_args(argv):
    opts = {"view": S.LIVE, "date": None, "snapshot": None, "team": None,
            "help": False, "list_teams": False}
    i = 0
    name_to_view = {"live": S.LIVE, "schedule": S.SCHEDULE, "groups": S.GROUPS,
                    "bracket": S.BRACKET, "scorers": S.SCORERS, "help": S.HELP}
    while i < len(argv):
        a = argv[i]
        al = a.lower()
        if a in ("--date", "-d") and i + 1 < len(argv):
            opts["date"] = argv[i + 1]
            opts["view"] = S.SCHEDULE
            i += 2
        elif a == "--snapshot" and i + 1 < len(argv):
            opts["snapshot"] = argv[i + 1]
            i += 2
        elif a in ("--team", "-t") and i + 1 < len(argv):
            opts["team"] = argv[i + 1]
            opts["view"] = S.TEAM
            i += 2
        elif a in ("--help", "-h"):
            opts["help"] = True
            i += 1
        elif al in ("--teams", "--list"):
            opts["list_teams"] = True
            i += 1
        elif al in name_to_view:
            opts["view"] = name_to_view[al]
            i += 1
        elif a.startswith("--") and len(a) > 2:
            # any other --FLAG is treated as a team code/name, e.g. --ENG
            opts["team"] = a[2:]
            opts["view"] = S.TEAM
            i += 1
        elif not a.startswith("-"):
            # bare word: a team name/abbr, e.g.  wcup england  /  wcup eng
            opts["team"] = a
            opts["view"] = S.TEAM
            i += 1
        else:
            i += 1
    return opts


def list_teams():
    espn.fetch_team_colors()
    seen = {}
    for k, rec in espn._team_colors.items():
        if rec.get("abbr") and rec.get("name"):
            seen[rec["abbr"]] = rec["name"]
    print("FIFA World Cup 2026 — team codes (use:  wcup --CODE)\n")
    items = sorted(seen.items(), key=lambda kv: kv[1])
    for abbr, name in items:
        print(f"  --{abbr:<4} {name}")
    print(f"\n{len(items)} teams.")


def start_team(st, app, refresher, query):
    """Resolve a team query and load its page synchronously for first paint."""
    res = S.open_team(st, app, query, refresher)
    if getattr(st, "team_abbr", None) and app.view == S.TEAM:
        refresher._do_team(st.team_abbr, getattr(st, "team_query", ""), force=True)
    else:
        app.goto(S.LIVE)
        app.toast(f"{res} — showing live scores", "error", 7)
    return res


def snapshot(opts):
    """Render one frame to stdout (for non-interactive validation)."""
    try:
        cols, rows = opts["snapshot"].lower().split("x")
        cols, rows = int(cols), int(rows)
    except ValueError:
        cols, rows = 120, 40
    st = S.AppState()
    refresher = S.Refresher(st)
    app = build_app(st, refresher)
    seed_view(app, opts["view"])
    if opts["date"]:
        st.schedule_date = opts["date"]
    initial_load(st, refresher)
    if opts.get("team"):
        start_team(st, app, refresher, opts["team"])
    # synchronously load the active view's data
    if app.view == S.SCHEDULE:
        refresher._do_schedule(st.schedule_date, force=True)
    elif app.view == S.GROUPS:
        refresher._do_standings(force=True)
    elif app.view == S.BRACKET:
        refresher._do_bracket(force=True)
    elif app.view == S.SCORERS:
        refresher._do_scorers(force=True)
    lines = render_frame(app, cols, rows)
    sys.stdout.write("\n".join(lines) + term.RESET + "\n")


def main():
    opts = parse_args(sys.argv[1:])
    if opts["help"]:
        print(USAGE)
        return
    if opts["list_teams"]:
        list_teams()
        return
    if opts["snapshot"]:
        snapshot(opts)
        return
    if not sys.stdin.isatty():
        print("worldcup: needs an interactive terminal (or use --snapshot WxH).")
        return

    st = S.AppState()
    if opts["date"]:
        st.schedule_date = opts["date"]
    refresher = S.Refresher(st)
    app = build_app(st, refresher)
    seed_view(app, opts["view"])
    initial_load(st, refresher)
    if opts["team"]:
        start_team(st, app, refresher, opts["team"])
    refresher.start()
    if app.view == S.SCHEDULE:
        refresher.request_schedule(st.schedule_date)

    app.run(views.draw_frame)
    st.running = False
    print("⚽ thanks for watching — full time.")


if __name__ == "__main__":
    main()
