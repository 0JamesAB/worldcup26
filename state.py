"""
state.py - Application state, the command registry feeding the puretui command
palette, and the background refresher thread that keeps live data flowing.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import espn
from puretui.app import Toast, Toasts
from puretui.interact import ListState, ScrollState

FAR = datetime.max.replace(tzinfo=timezone.utc)

# View identifiers
LIVE = "live"
SCHEDULE = "schedule"
GROUPS = "groups"
BRACKET = "bracket"
SCORERS = "scorers"
DETAIL = "detail"
TEAM = "team"
HELP = "help"

TABS = [("1", "Live"), ("2", "Schedule"), ("3", "Groups"),
        ("4", "Bracket"), ("5", "Scorers")]
TAB_VIEWS = [LIVE, SCHEDULE, GROUPS, BRACKET, SCORERS]


def today_yyyymmdd():
    return datetime.now().astimezone().strftime("%Y%m%d")


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        # The puretui.app.App this state is wired to (installed by
        # wc.build_app). Its view stack is the routing authority; the
        # `view`/`dirty` properties below read through to it, and fall
        # back to plain fields for standalone states (fixtures, tools).
        self.app = None
        self._view = LIVE
        self.running = True
        self._dirty = True

        # data
        self.matches_today = []          # list[Match]
        self.today_label = ""
        self.schedule_date = today_yyyymmdd()
        self.schedule_matches = []
        self.schedule_label = ""
        self.standings = []              # list[Group]
        self.bracket = {}                # slug -> list[Match]
        self.scorers = {"goals": [], "assists": []}
        self.summaries = {}              # event_id -> MatchDetail
        self.match_index = {}            # event_id -> Match (for detail header)

        # selection / scroll
        self.live_ls = ListState()
        self.sched_ls = ListState()      # schedule and team share the cursor
        self.scorers_ls = ListState()
        self.groups_ss = ScrollState()
        self.bracket_ss_x = ScrollState()
        self.bracket_ss_y = ScrollState()
        self.scorers_tab = 0             # 0 goals, 1 assists
        self.detail_event_id = None
        self.detail_tab = 0              # 0 lineups, 1 timeline, 2 stats
        self.detail_ss = ScrollState()

        # toasts / notifications (shared with app.toasts by wc.build_app)
        self.toasts = Toasts(limit=6)
        self._signatures = {}            # event_id -> signature (goal detection)
        self._first_sig_pass = True

        # status
        self.status = "starting…"
        self.loading = set()

        # navigation hooks: wc.py installs callables that views.py's
        # click closures route through (opening the match centre,
        # switching the active view, shifting the schedule day).
        self.open_match = None
        self.change_view = None
        self.sched_day = None

    # -- routing state, read through the attached App --

    @property
    def view(self):
        """The active view name: top of the App's view stack once wired."""
        app = self.app
        if app is not None and app.stack:
            return app.stack[-1]
        return self._view

    @view.setter
    def view(self, v):
        app = self.app
        if app is not None:
            app.goto(v)
        else:
            self._view = v

    @property
    def dirty(self):
        app = self.app
        return app.dirty if app is not None else self._dirty

    @dirty.setter
    def dirty(self, v):
        app = self.app
        if app is not None:
            app.dirty = v
        else:
            self._dirty = v

    # -- int shims over the ListState cursors (fixtures + tests) --
    @property
    def live_sel(self):
        return self.live_ls.sel

    @live_sel.setter
    def live_sel(self, v):
        self.live_ls.sel = v

    @property
    def sched_sel(self):
        return self.sched_ls.sel

    @sched_sel.setter
    def sched_sel(self, v):
        self.sched_ls.sel = v

    @property
    def scorers_sel(self):
        return self.scorers_ls.sel

    @scorers_sel.setter
    def scorers_sel(self, v):
        self.scorers_ls.sel = v

    # -- int shims over the ScrollState offsets (fixtures + tests) --
    # Raw offset reads/writes, exactly like the old plain-int fields:
    # each view's render clamps via set_extent (overshoot stays until then).
    @property
    def groups_scroll(self):
        return self.groups_ss.offset

    @groups_scroll.setter
    def groups_scroll(self, v):
        self.groups_ss.offset = v

    @property
    def bracket_scroll_x(self):
        return self.bracket_ss_x.offset

    @bracket_scroll_x.setter
    def bracket_scroll_x(self, v):
        self.bracket_ss_x.offset = v

    @property
    def bracket_scroll_y(self):
        return self.bracket_ss_y.offset

    @bracket_scroll_y.setter
    def bracket_scroll_y(self, v):
        self.bracket_ss_y.offset = v

    @property
    def detail_scroll(self):
        return self.detail_ss.offset

    @detail_scroll.setter
    def detail_scroll(self, v):
        self.detail_ss.offset = v

    # -- toast helpers --
    def toast(self, text, kind="info", ttl=8.0):
        with self.lock:
            self.toasts.add(text, kind, ttl)
            self.dirty = True

    # -- goal detection on a fresh today/scoreboard fetch --
    def detect_goals(self, matches):
        new_sigs = {}
        for m in matches:
            sig = m.signature()
            new_sigs[m.id] = sig
            old = self._signatures.get(m.id)
            if old and old != sig and not self._first_sig_pass:
                self._maybe_goal_toast(m, old)
        self._signatures = new_sigs
        self._first_sig_pass = False

    def _maybe_goal_toast(self, m, old_sig):
        # old_sig format id:home:away:state:clock
        try:
            _, oh, oa, ostate, _ = old_sig.split(":", 4)
        except ValueError:
            return
        if not m.home or not m.away:
            return
        nh = m.home.score
        na = m.away.score
        try:
            scored = (int(nh) > int(oh)) or (int(na) > int(oa))
        except (TypeError, ValueError):
            scored = False
        if scored:
            self.toast(
                f"⚽ GOAL!  {m.away.abbr} {m.away.score} - {m.home.score} {m.home.abbr}",
                kind="goal", ttl=12.0)
        elif ostate == "in" and m.state == "post":
            self.toast(
                f"FT  {m.away.abbr} {m.away.score} - {m.home.score} {m.home.abbr}",
                kind="info", ttl=8.0)
        elif ostate == "pre" and m.state == "in":
            self.toast(f"KICK-OFF  {m.away.abbr} v {m.home.abbr}", kind="info")


# ----------------------------------------------------------------------------
# Command registry (puretui.commands specs)
# ----------------------------------------------------------------------------

def _unique_teams():
    colors = espn.fetch_team_colors()
    seen = {}
    for rec in colors.values():
        if rec.get("abbr") and rec.get("name"):
            seen[rec["abbr"]] = rec["name"]
    return sorted(seen.items(), key=lambda kv: kv[1])


# -- completion providers: each returns a callable(arg) -> (title, rows) --

def _complete_team(name):
    def complete(arg):
        al = arg.lower()
        out = []
        for abbr, tname in _unique_teams():
            if al == "" or al in abbr.lower() or al in tname.lower():
                out.append({"text": f"{name} {abbr}", "label": tname,
                            "hint": "--" + abbr, "kind": "arg"})
        return (f"Teams · {len(out)}", out[:9])
    return complete


def _complete_group(st, name):
    def complete(arg):
        al = arg.lower()
        letters = [g.name.split()[-1] for g in st.standings] or list("ABCDEFGHIJKL")
        out = [{"text": f"{name} {L}", "label": f"Group {L}", "hint": "", "kind": "arg"}
               for L in letters if al == "" or L.lower().startswith(al)]
        return ("Groups", out)
    return complete


def _complete_date(name):
    def complete(arg):
        al = arg.lower()
        opts = [("today", "today"), ("tomorrow", "+1 day"), ("yesterday", "-1 day"),
                ("+1", "next day"), ("-1", "previous day"), ("+7", "in a week"),
                ("20260703", "a specific YYYYMMDD")]
        out = [{"text": f"{name} {v}", "label": v, "hint": h, "kind": "arg"}
               for v, h in opts if al == "" or v.startswith(al)]
        return ("Date  (YYYYMMDD · today · +N · -N)", out)
    return complete


def _complete_match(st, name):
    def complete(arg):
        al = arg.lower()
        out = []
        for m in (st.matches_today or []):
            lbl = f"{m.away.abbr if m.away else '?'} v {m.home.abbr if m.home else '?'}"
            if al == "" or m.id.startswith(arg):
                out.append({"text": f"{name} {m.id}", "label": m.id,
                            "hint": lbl, "kind": "arg"})
        return ("Today's match ids", out[:9])
    return complete


def _complete_onoff(name):
    def complete(arg):
        al = arg.lower()
        out = [{"text": f"{name} {v}", "label": v, "hint": h, "kind": "arg"}
               for v, h in (("on", "capture clicks & wheel"),
                            ("off", "native text selection"))
               if al == "" or v.startswith(al)]
        return ("Mouse", out)
    return complete


def command_specs(st, app, refresher):
    """Build the puretui.commands spec list for one (state, app, refresher).

    The run closures capture exactly what they need; completion comes
    from the small providers above. Called with Nones only to read the
    static fields (see HELP_COMMANDS) — no closure runs then.
    """

    def go(view):
        app.goto(view)
        refresher.wake()     # fetch the new view's data promptly

    def run_live(arg):
        go(LIVE)
        return "live scores"

    def run_schedule(arg):
        if arg:
            d = resolve_date(arg, st.schedule_date)
            if d:
                st.schedule_date = d
        go(SCHEDULE)
        refresher.request_schedule(st.schedule_date)
        return f"schedule {st.schedule_date}"

    def run_date(arg):
        d = resolve_date(arg, st.schedule_date)
        if not d:
            return f"bad date: {arg}"
        st.schedule_date = d
        go(SCHEDULE)
        refresher.request_schedule(d)
        return f"date -> {d}"

    def run_groups(arg):
        go(GROUPS)
        if arg:
            letter = arg.split()[0].upper()
            for i, gp in enumerate(st.standings):
                if gp.name.upper().endswith(letter):
                    st.groups_ss.offset = i
                    break
        return "group tables"

    def run_bracket(arg):
        go(BRACKET)
        return "bracket"

    def run_scorers(arg):
        go(SCORERS)
        st.scorers_tab = 0
        return "top scorers"

    def run_assists(arg):
        go(SCORERS)
        st.scorers_tab = 1
        return "top assists"

    def run_team(arg):
        if not arg:
            return "usage: :team <name>"
        return open_team(st, app, arg, refresher)

    def run_match(arg):
        if not arg:
            return "usage: :match <event id>"
        eid = arg.split()[0]
        st.detail_event_id = eid
        st.detail_tab = 0
        if st.view != DETAIL:
            app.push(DETAIL)
        refresher.request_summary(eid)
        return f"match {eid}"

    def run_mouse(arg):
        arg = arg.lower()
        if arg in ("on", "off"):
            app.mouse_enabled = arg == "on"
        elif not arg:
            app.mouse_enabled = not app.mouse_enabled
        else:
            return "usage: :mouse [on|off]"
        return "mouse " + ("on" if app.mouse_enabled
                           else "off — native text selection restored")

    def run_refresh(arg):
        refresher.force_all()
        return "refreshing…"

    def run_help(arg):
        if st.view != HELP:
            app.push(HELP)
        return "help"

    def run_quit(arg):
        st.running = False
        app.quit()
        return "bye"

    return [
        {"name": "live", "aliases": ["l", "today", "scores"],
         "syntax": "live", "desc": "live / today's scores",
         "run": run_live, "complete": None},
        {"name": "schedule", "aliases": ["sched", "s", "fixtures"],
         "syntax": "schedule [date]", "desc": "browse fixtures by day",
         "run": run_schedule, "complete": _complete_date("schedule")},
        {"name": "date", "aliases": ["d", "goto"],
         "syntax": "date <day>", "desc": "set the schedule date",
         "run": run_date, "complete": _complete_date("date")},
        {"name": "groups", "aliases": ["group", "g", "table", "standings"],
         "syntax": "groups [A-L]", "desc": "group tables",
         "run": run_groups, "complete": _complete_group(st, "groups")},
        {"name": "bracket", "aliases": ["b", "knockout", "ko"],
         "syntax": "bracket", "desc": "knockout bracket",
         "run": run_bracket, "complete": None},
        {"name": "scorers", "aliases": ["scorer", "goals", "boot", "golden"],
         "syntax": "scorers", "desc": "golden boot leaderboard",
         "run": run_scorers, "complete": None},
        {"name": "assists", "aliases": ["assist"],
         "syntax": "assists", "desc": "assist leaderboard",
         "run": run_assists, "complete": None},
        {"name": "team", "aliases": ["t", "nation"],
         "syntax": "team <name|ABBR>", "desc": "a nation's results & fixtures",
         "run": run_team, "complete": _complete_team("team")},
        {"name": "match", "aliases": ["m", "game"],
         "syntax": "match <id>", "desc": "open a match by event id",
         "run": run_match, "complete": _complete_match(st, "match")},
        {"name": "refresh", "aliases": ["r", "reload"],
         "syntax": "refresh", "desc": "force a refresh now",
         "run": run_refresh, "complete": None},
        {"name": "mouse", "aliases": [],
         "syntax": "mouse [on|off]",
         "desc": "toggle mouse capture (off = native text selection)",
         "run": run_mouse, "complete": _complete_onoff("mouse")},
        {"name": "help", "aliases": ["h", "?"],
         "syntax": "help", "desc": "keys & commands",
         "run": run_help, "complete": None},
        {"name": "quit", "aliases": ["q", "exit"],
         "syntax": "quit", "desc": "exit",
         "run": run_quit, "complete": None},
    ]


HELP_COMMANDS = [(":" + c["syntax"], c["desc"])
                 for c in command_specs(None, None, None)]


def resolve_date(token, base=None):
    base = base or today_yyyymmdd()
    token = token.strip().lower()
    if token in ("", "today", "now"):
        return today_yyyymmdd()
    if token in ("tomorrow", "tmrw"):
        d = datetime.strptime(base, "%Y%m%d") + timedelta(days=1)
        return d.strftime("%Y%m%d")
    if token in ("yesterday", "yest"):
        d = datetime.strptime(base, "%Y%m%d") - timedelta(days=1)
        return d.strftime("%Y%m%d")
    if token and token[0] in "+-" and token[1:].isdigit():
        d = datetime.strptime(base, "%Y%m%d") + timedelta(days=int(token))
        return d.strftime("%Y%m%d")
    if len(token) == 8 and token.isdigit():
        return token
    return None


def open_team(st, app, query, refresher):
    """Find a nation by name/abbr and open its team page (pushed, so
    Esc returns to wherever it was opened from)."""
    q = query.strip().lower()
    colors = espn.fetch_team_colors()
    best = None
    for k, rec in colors.items():
        name = (rec.get("name") or "")
        abbr = (rec.get("abbr") or "")
        if not name:
            continue
        nl = name.lower()
        if q == abbr.lower() or q == nl:
            best = rec
            break
        if q in nl and best is None:
            best = rec
    if not best:
        return f"no team: {query}"
    st.team_query = best.get("name")
    st.team_abbr = best.get("abbr")
    if st.view != TEAM:
        app.push(TEAM)
    refresher.request_team(best.get("abbr"), best.get("name"))
    return f"team {best.get('name')}"


# ----------------------------------------------------------------------------
# Background refresher
# ----------------------------------------------------------------------------

class Refresher(threading.Thread):
    """Single daemon thread that keeps the active view's data fresh."""

    INTERVALS = {
        "today": 12,
        "schedule": 25,
        "standings": 90,
        "bracket": 45,
        "scorers": 240,
        "summary": 15,
        "team": 120,
    }

    def __init__(self, state):
        super().__init__(daemon=True)
        self.state = state
        self._last = {}
        self._requests = []
        self._req_lock = threading.Lock()
        self._wake = threading.Event()
        self._force = set()

    # --- external requests ---
    def _enqueue(self, fn):
        with self._req_lock:
            self._requests.append(fn)
        self._wake.set()

    def request_schedule(self, date):
        self._enqueue(lambda: self._do_schedule(date, force=True))

    def request_summary(self, event_id):
        self._enqueue(lambda: self._do_summary(event_id, force=True))

    def request_team(self, abbr, name):
        self._enqueue(lambda: self._do_team(abbr, name, force=True))

    def force_all(self):
        espn.clear_cache()
        self._force = {"today", "schedule", "standings", "bracket", "scorers", "summary", "team"}
        self._wake.set()

    def wake(self):
        self._wake.set()

    def _due(self, key):
        if key in self._force:
            return True
        return (time.time() - self._last.get(key, 0)) >= self.INTERVALS.get(key, 30)

    def _stamp(self, key):
        self._last[key] = time.time()
        self._force.discard(key)

    # --- run loop ---
    def run(self):
        st = self.state
        while st.running:
            # process explicit requests first
            with self._req_lock:
                reqs, self._requests = self._requests, []
            for fn in reqs:
                try:
                    fn()
                except Exception as e:
                    st.status = f"err: {e}"
            try:
                self._tick()
            except Exception as e:
                st.status = f"err: {e}"
            self._wake.wait(timeout=2.0)
            self._wake.clear()

    def _tick(self):
        st = self.state
        # Always keep today's scoreboard fresh (live ticker + notifications).
        if self._due("today"):
            self._do_today()
        view = st.view
        if view == SCHEDULE and self._due("schedule"):
            self._do_schedule(st.schedule_date)
        elif view == GROUPS and self._due("standings"):
            self._do_standings()
        elif view == BRACKET and self._due("bracket"):
            self._do_bracket()
        elif view == SCORERS and self._due("scorers"):
            self._do_scorers()
        elif view == DETAIL and st.detail_event_id and self._due("summary"):
            self._do_summary(st.detail_event_id)
        elif view == TEAM and self._due("team"):
            if getattr(st, "team_abbr", None):
                self._do_team(st.team_abbr, getattr(st, "team_query", ""))

    # --- fetchers ---
    def _set_status(self, msg):
        self.state.status = msg

    def _do_today(self, force=False):
        st = self.state
        try:
            matches, label = espn.fetch_matches(today_yyyymmdd(), ttl=10, force=force)
            with st.lock:
                st.detect_goals(matches)
                st.matches_today = matches
                st.today_label = label
                for m in matches:
                    st.match_index[m.id] = m
                st.dirty = True
            self._stamp("today")
            self._set_status(f"updated {datetime.now().strftime('%H:%M:%S')}")
        except espn.ApiError as e:
            self._set_status(f"offline · {e}")

    def _do_schedule(self, date, force=False):
        st = self.state
        st.loading.add("schedule")
        try:
            matches, label = espn.fetch_matches(date, ttl=20, force=force)
            with st.lock:
                if st.schedule_date == date or force:
                    st.schedule_matches = matches
                    st.schedule_label = label
                for m in matches:
                    st.match_index[m.id] = m
                st.dirty = True
            self._stamp("schedule")
        except espn.ApiError as e:
            self._set_status(f"offline · {e}")
        finally:
            st.loading.discard("schedule")

    def _do_standings(self, force=False):
        st = self.state
        try:
            groups = espn.fetch_standings(force=force)
            with st.lock:
                st.standings = groups
                st.dirty = True
            self._stamp("standings")
        except espn.ApiError as e:
            self._set_status(f"offline · {e}")

    def _do_bracket(self, force=False):
        st = self.state
        try:
            br = espn.fetch_bracket(force=force)
            with st.lock:
                st.bracket = br
                for ms in br.values():
                    for m in ms:
                        st.match_index[m.id] = m
                st.dirty = True
            self._stamp("bracket")
        except espn.ApiError as e:
            self._set_status(f"offline · {e}")

    def _do_scorers(self, force=False):
        st = self.state
        st.loading.add("scorers")
        try:
            sc = espn.fetch_scorers(limit=20, force=force)
            with st.lock:
                st.scorers = sc
                st.dirty = True
            self._stamp("scorers")
        except espn.ApiError as e:
            self._set_status(f"offline · {e}")
        finally:
            st.loading.discard("scorers")

    def _do_summary(self, event_id, force=False):
        st = self.state
        st.loading.add("summary")
        try:
            detail = espn.fetch_summary(event_id, force=force)
            with st.lock:
                st.summaries[event_id] = detail
                st.dirty = True
            self._stamp("summary")
        except espn.ApiError as e:
            self._set_status(f"offline · {e}")
        finally:
            st.loading.discard("summary")

    def _do_team(self, abbr, name, force=False):
        st = self.state
        st.loading.add("team")
        try:
            # gather a team's matches across the whole tournament
            matches, _ = espn.fetch_matches("20260611-20260720", ttl=60, force=force)
            mine = [m for m in matches
                    if (m.home and m.home.abbr == abbr) or (m.away and m.away.abbr == abbr)]
            mine.sort(key=lambda m: (m.date or FAR))
            with st.lock:
                st.team_matches = mine
                st.dirty = True
            self._stamp("team")
        except espn.ApiError as e:
            self._set_status(f"offline · {e}")
        finally:
            st.loading.discard("team")
