#!/usr/bin/env python3
"""
wc.py - World Cup 2026 terminal dashboard. Entry point + input loop.

Usage:
    python3 wc.py                 # launch the live dashboard
    python3 wc.py groups          # start on a given view (live/schedule/groups/bracket/scorers)
    python3 wc.py --date 20260703 # start on the schedule for a date
    python3 wc.py --snapshot 120x40 [view]   # render one frame to stdout and exit (no TTY)

Keys:  1-5 views · Tab cycle · ↑↓ move · ←→ day/tabs/scroll · Enter open
       : command line · r refresh · ? help · q quit
"""

import sys
import time
from datetime import datetime, timezone

FAR = datetime.max.replace(tzinfo=timezone.utc)

from tui import term
from tui.term import Key, RawTerminal, Renderer, read_key
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


def current_list(st):
    if st.view == S.LIVE:
        return live_ordered(st), "live_sel"
    if st.view == S.SCHEDULE:
        return list(st.schedule_matches), "sched_sel"
    if st.view == S.TEAM:
        return list(getattr(st, "team_matches", [])), "sched_sel"
    if st.view == S.SCORERS:
        key = "goals" if st.scorers_tab == 0 else "assists"
        return list(st.scorers.get(key, [])), "scorers_sel"
    return [], None


def open_match(st, refresher, event_id):
    """Jump to the match centre for an event id."""
    st.detail_event_id = event_id
    if st.view != S.DETAIL:
        st.prev_view = st.view
    st.view = S.DETAIL
    st.detail_tab = 0
    st.detail_scroll = 0
    refresher.request_summary(event_id)


def open_selected(st, refresher):
    lst, attr = current_list(st)
    if not lst or attr is None or st.view == S.SCORERS:
        return
    idx = max(0, min(getattr(st, attr), len(lst) - 1))
    open_match(st, refresher, lst[idx].id)


def move_selection(st, delta):
    lst, attr = current_list(st)
    if attr is None:
        return
    n = len(lst)
    if n == 0:
        return
    cur = getattr(st, attr)
    setattr(st, attr, max(0, min(cur + delta, n - 1)))


def change_view(st, view):
    if view == st.view:
        return
    if st.view not in (S.DETAIL, S.HELP, S.TEAM):
        st.prev_view = st.view
    st.view = view


def cycle_view(st, direction):
    views_order = S.TAB_VIEWS
    cur = st.view if st.view in views_order else st.prev_view
    i = views_order.index(cur) if cur in views_order else 0
    change_view(st, views_order[(i + direction) % len(views_order)])


def handle_normal_key(st, key, refresher):
    if key in ("q", "Q"):
        st.running = False
    elif key in (":", "/"):
        st.command_mode = True
        st.command_buf = ""
    elif key in ("?",):
        change_view(st, S.HELP)
    elif key in ("r", "R"):
        refresher.force_all()
        st.toast("refreshing…", "info", 3)
    elif key in ("1", "2", "3", "4", "5"):
        change_view(st, S.TAB_VIEWS[int(key) - 1])
    elif key == Key.TAB:
        cycle_view(st, 1)
    elif key == Key.SHIFT_TAB:
        cycle_view(st, -1)
    elif key == Key.ESC:
        if st.view in (S.DETAIL, S.HELP, S.TEAM):
            st.view = st.prev_view or S.LIVE
    elif key == Key.ENTER:
        if st.view in (S.LIVE, S.SCHEDULE, S.TEAM):
            open_selected(st, refresher)
    elif key in (Key.UP, "k"):
        nav_vertical(st, -1)
    elif key in (Key.DOWN, "j"):
        nav_vertical(st, 1)
    elif key in (Key.LEFT, "h"):
        nav_horizontal(st, -1, refresher)
    elif key in (Key.RIGHT, "l"):
        nav_horizontal(st, 1, refresher)
    elif key == Key.PGUP:
        nav_vertical(st, -5)
    elif key == Key.PGDN:
        nav_vertical(st, 5)
    elif key == Key.HOME:
        nav_vertical(st, -9999)
    elif key == Key.END:
        nav_vertical(st, 9999)


def handle_mouse(st, ev, refresher):
    """Route a MouseEvent: wheel scrolls, left-click hits a region.

    Click semantics: clicking a list item / card selects it; clicking the
    already-selected one opens it (match centre). Tabs, date arrows and
    bracket cells act immediately.
    """
    if ev.kind == "wheel":
        nav_vertical(st, 1 if ev.button == "wheel_down" else -1)
        return
    if ev.kind != "press" or ev.button != "left":
        return
    action = st.hits.lookup(ev.row, ev.col)
    if not action:
        return
    kind = action[0]
    if kind == "view":
        change_view(st, action[1])
    elif kind == "sel":
        _, attr, i, openable = action
        if openable and getattr(st, attr, None) == i:
            open_selected(st, refresher)
        else:
            setattr(st, attr, i)
    elif kind == "open":
        open_match(st, refresher, action[1])
    elif kind == "scorers_tab":
        st.scorers_tab = action[1]
        st.scorers_sel = 0
    elif kind == "detail_tab":
        st.detail_tab = action[1]
        st.detail_scroll = 0
    elif kind == "sched_day":
        d = S.resolve_date(("+" if action[1] > 0 else "-") + "1", st.schedule_date)
        if d:
            st.schedule_date = d
            st.sched_sel = 0
            refresher.request_schedule(d)


def nav_vertical(st, delta):
    if st.view == S.GROUPS:
        st.groups_scroll = max(0, st.groups_scroll + (1 if delta > 0 else -1))
    elif st.view == S.BRACKET:
        st.bracket_scroll_y = max(0, st.bracket_scroll_y + delta * 2)
    elif st.view == S.DETAIL:
        st.detail_scroll = max(0, st.detail_scroll + (1 if delta > 0 else -1))
    else:
        move_selection(st, delta)


def nav_horizontal(st, delta, refresher):
    if st.view == S.SCHEDULE:
        d = S.resolve_date(("+" if delta > 0 else "-") + "1", st.schedule_date)
        if d:
            st.schedule_date = d
            st.sched_sel = 0
            refresher.request_schedule(d)
    elif st.view == S.SCORERS:
        st.scorers_tab = (st.scorers_tab + delta) % 2
        st.scorers_sel = 0
    elif st.view == S.DETAIL:
        st.detail_tab = (st.detail_tab + delta) % len(views.DETAIL_TABS)
        st.detail_scroll = 0
    elif st.view == S.BRACKET:
        st.bracket_scroll_x = max(0, st.bracket_scroll_x + delta * 6)
    elif st.view == S.GROUPS:
        pass


def complete_command(st):
    """Tab: fill the buffer with the currently-highlighted suggestion."""
    title, sugg = S.command_completions(st, st.command_buf)
    if not sugg:
        return
    sel = sugg[min(st.command_sel, len(sugg) - 1)]
    st.command_buf = sel["text"]
    st.command_sel = 0


def move_command_sel(st, delta):
    _, sugg = S.command_completions(st, st.command_buf)
    n = len(sugg)
    if n:
        st.command_sel = (st.command_sel + delta) % n


def handle_command_key(st, key, refresher):
    if key == Key.ENTER:
        cmd = st.command_buf
        st.command_mode = False
        st.command_buf = ""
        st.command_sel = 0
        res = S.run_command(st, cmd, refresher)
        if res:
            st.toast(res, "info", 4)
    elif key == Key.ESC:
        st.command_mode = False
        st.command_buf = ""
        st.command_sel = 0
    elif key == Key.TAB:
        complete_command(st)
    elif key in (Key.UP, Key.SHIFT_TAB):
        move_command_sel(st, -1)
    elif key == Key.DOWN:
        move_command_sel(st, 1)
    elif key == Key.BACKSPACE:
        st.command_buf = st.command_buf[:-1]
        st.command_sel = 0
    elif isinstance(key, str) and len(key) == 1 and key.isprintable():
        st.command_buf += key
        st.command_sel = 0


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


def snapshot(opts):
    """Render one frame to stdout (for non-interactive validation)."""
    try:
        cols, rows = opts["snapshot"].lower().split("x")
        cols, rows = int(cols), int(rows)
    except ValueError:
        cols, rows = 120, 40
    st = S.AppState()
    st.view = opts["view"]
    refresher = S.Refresher(st)
    if opts["date"]:
        st.schedule_date = opts["date"]
    initial_load(st, refresher)
    if opts.get("team"):
        start_team(st, refresher, opts["team"])
    # synchronously load the active view's data
    if st.view == S.SCHEDULE:
        refresher._do_schedule(st.schedule_date, force=True)
    elif st.view == S.GROUPS:
        refresher._do_standings(force=True)
    elif st.view == S.BRACKET:
        refresher._do_bracket(force=True)
    elif st.view == S.SCORERS:
        refresher._do_scorers(force=True)
    lines = views.render(st, cols, rows)
    sys.stdout.write("\n".join(lines) + term.RESET + "\n")


def start_team(st, refresher, query):
    """Resolve a team query and load its page synchronously for first paint."""
    res = S.open_team(st, query, refresher)
    if getattr(st, "team_abbr", None) and st.view == S.TEAM:
        refresher._do_team(st.team_abbr, getattr(st, "team_query", ""), force=True)
    else:
        st.view = S.LIVE
        st.toast(f"{res} — showing live scores", "error", 7)
    return res


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
    st.view = opts["view"]
    if opts["date"]:
        st.schedule_date = opts["date"]
    refresher = S.Refresher(st)
    initial_load(st, refresher)
    if opts["team"]:
        start_team(st, refresher, opts["team"])
    refresher.start()
    if st.view == S.SCHEDULE:
        refresher.request_schedule(st.schedule_date)

    renderer = Renderer()
    last_tick = 0.0
    try:
        with RawTerminal(mouse=True) as tw:
            while st.running:
                if tw.take_resize():
                    renderer.reset()
                    st.dirty = True
                if tw.mouse != st.mouse_enabled:   # :mouse on|off
                    tw.set_mouse(st.mouse_enabled)
                key = read_key(timeout=0.12)
                if key is not None:
                    if isinstance(key, term.MouseEvent):
                        if not st.command_mode and st.mouse_enabled:
                            handle_mouse(st, key, refresher)
                    elif st.command_mode:
                        handle_command_key(st, key, refresher)
                    else:
                        handle_normal_key(st, key, refresher)
                    refresher.wake()
                    st.dirty = True
                st.prune_toasts()
                now = time.time()
                # animate (clock, pulse, cursor) ~3x/sec
                if now - last_tick >= 0.33:
                    st.dirty = True
                    last_tick = now
                if st.dirty:
                    size = term.terminal_size()
                    lines = views.render(st, size[0], size[1])
                    renderer.render(lines, size)
                    st.dirty = False
    except KeyboardInterrupt:
        pass
    finally:
        st.running = False
    print("⚽ thanks for watching — full time.")


if __name__ == "__main__":
    main()
