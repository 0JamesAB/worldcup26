"""
state.py - Application state, the command-line ("/" -> ":" vim-style) parser,
and the background refresher thread that keeps live data flowing.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import espn
from tui.interact import HitMap

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


class Toast:
    def __init__(self, text, kind="info", ttl=8.0):
        self.text = text
        self.kind = kind          # info | goal | error
        self.born = time.time()
        self.ttl = ttl

    @property
    def alive(self):
        return (time.time() - self.born) < self.ttl

    @property
    def age(self):
        return time.time() - self.born


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.hits = HitMap()   # clickable regions, rebuilt every rendered frame
        self.view = LIVE
        self.prev_view = LIVE
        self.running = True
        self.dirty = True
        self.frame = 0

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
        self.live_sel = 0
        self.sched_sel = 0
        self.groups_scroll = 0
        self.bracket_scroll_x = 0
        self.bracket_scroll_y = 0
        self.scorers_tab = 0             # 0 goals, 1 assists
        self.scorers_sel = 0
        self.detail_event_id = None
        self.detail_tab = 0              # 0 lineups, 1 timeline, 2 stats
        self.detail_scroll = 0

        # command line
        self.command_mode = False
        self.command_buf = ""
        self.command_result = ""
        self.command_sel = 0

        # toasts / notifications
        self.toasts = []
        self._signatures = {}            # event_id -> signature (goal detection)
        self._first_sig_pass = True

        # status
        self.status = "starting…"
        self.loading = set()

    # -- toast helpers --
    def toast(self, text, kind="info", ttl=8.0):
        with self.lock:
            self.toasts.append(Toast(text, kind, ttl))
            self.toasts = [t for t in self.toasts if t.alive][-6:]
            self.dirty = True

    def prune_toasts(self):
        with self.lock:
            before = len(self.toasts)
            self.toasts = [t for t in self.toasts if t.alive]
            if len(self.toasts) != before:
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
# Command line
# ----------------------------------------------------------------------------

# Command registry. `args` is one of: None, "date", "group", "team", "match".
COMMANDS = [
    {"name": "live", "aliases": ["l", "today", "scores"], "args": None,
     "syntax": "live", "desc": "live / today's scores"},
    {"name": "schedule", "aliases": ["sched", "s", "fixtures"], "args": "date",
     "syntax": "schedule [date]", "desc": "browse fixtures by day"},
    {"name": "date", "aliases": ["d", "goto"], "args": "date",
     "syntax": "date <day>", "desc": "set the schedule date"},
    {"name": "groups", "aliases": ["group", "g", "table", "standings"], "args": "group",
     "syntax": "groups [A-L]", "desc": "group tables"},
    {"name": "bracket", "aliases": ["b", "knockout", "ko"], "args": None,
     "syntax": "bracket", "desc": "knockout bracket"},
    {"name": "scorers", "aliases": ["scorer", "goals", "boot", "golden"], "args": None,
     "syntax": "scorers", "desc": "golden boot leaderboard"},
    {"name": "assists", "aliases": ["assist"], "args": None,
     "syntax": "assists", "desc": "assist leaderboard"},
    {"name": "team", "aliases": ["t", "nation"], "args": "team",
     "syntax": "team <name|ABBR>", "desc": "a nation's results & fixtures"},
    {"name": "match", "aliases": ["m", "game"], "args": "match",
     "syntax": "match <id>", "desc": "open a match by event id"},
    {"name": "refresh", "aliases": ["r", "reload"], "args": None,
     "syntax": "refresh", "desc": "force a refresh now"},
    {"name": "help", "aliases": ["h"], "args": None,
     "syntax": "help", "desc": "keys & commands"},
    {"name": "quit", "aliases": ["q", "exit"], "args": None,
     "syntax": "quit", "desc": "exit"},
]

HELP_COMMANDS = [(":" + c["syntax"], c["desc"]) for c in COMMANDS]


def find_command(tok):
    tok = tok.lower()
    for c in COMMANDS:
        if tok == c["name"] or tok in c["aliases"]:
            return c
    # unique prefix match
    hits = [c for c in COMMANDS
            if c["name"].startswith(tok) or any(a.startswith(tok) for a in c["aliases"])]
    return hits[0] if len(hits) == 1 else None


def _unique_teams():
    colors = espn.fetch_team_colors()
    seen = {}
    for rec in colors.values():
        if rec.get("abbr") and rec.get("name"):
            seen[rec["abbr"]] = rec["name"]
    return sorted(seen.items(), key=lambda kv: kv[1])


def command_completions(st, buf):
    """Return (title, suggestions) for the command palette.

    Each suggestion: {text, label, hint, kind}. `text` is the new command
    buffer (without the leading ':') if accepted via Tab.
    """
    has_space = " " in buf
    if not has_space:
        prefix = buf.strip().lower()
        out = []
        for c in COMMANDS:
            names = [c["name"]] + c["aliases"]
            if prefix == "" or any(n.startswith(prefix) for n in names):
                text = c["name"] + (" " if c["args"] else "")
                out.append({"text": text, "label": ":" + c["syntax"],
                            "hint": c["desc"], "kind": "cmd"})
        return ("Commands", out)

    toks = buf.split(" ", 1)
    cmd = find_command(toks[0])
    arg = (toks[1] if len(toks) > 1 else "").strip()
    al = arg.lower()
    if not cmd:
        return ("?", [])
    name = cmd["name"]

    if cmd["args"] == "team":
        out = []
        for abbr, tname in _unique_teams():
            if al == "" or al in abbr.lower() or al in tname.lower():
                out.append({"text": f"{name} {abbr}", "label": tname,
                            "hint": "--" + abbr, "kind": "arg"})
        return (f"Teams · {len(out)}", out[:9])

    if cmd["args"] == "group":
        letters = [g.name.split()[-1] for g in st.standings] or list("ABCDEFGHIJKL")
        out = [{"text": f"{name} {L}", "label": f"Group {L}", "hint": "", "kind": "arg"}
               for L in letters if al == "" or L.lower().startswith(al)]
        return ("Groups", out)

    if cmd["args"] == "date":
        opts = [("today", "today"), ("tomorrow", "+1 day"), ("yesterday", "-1 day"),
                ("+1", "next day"), ("-1", "previous day"), ("+7", "in a week"),
                ("20260703", "a specific YYYYMMDD")]
        out = [{"text": f"{name} {v}", "label": v, "hint": h, "kind": "arg"}
               for v, h in opts if al == "" or v.startswith(al)]
        return ("Date  (YYYYMMDD · today · +N · -N)", out)

    if cmd["args"] == "match":
        out = []
        pool = (st.matches_today or [])
        for m in pool:
            lbl = f"{m.away.abbr if m.away else '?'} v {m.home.abbr if m.home else '?'}"
            if al == "" or m.id.startswith(arg):
                out.append({"text": f"{name} {m.id}", "label": m.id,
                            "hint": lbl, "kind": "arg"})
        return ("Today's match ids", out[:9])

    return (cmd["syntax"], [{"text": buf, "label": ":" + cmd["syntax"],
                            "hint": cmd["desc"], "kind": "info"}])


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


def run_command(state, raw, refresher):
    """Execute a command-line command. Returns a status string."""
    raw = raw.strip()
    if raw.startswith(":"):
        raw = raw[1:]
    if not raw:
        return ""
    parts = raw.split()
    cmd = parts[0].lower()
    args = parts[1:]
    arg = " ".join(args)

    if cmd in ("q", "quit", "exit"):
        state.running = False
        return "bye"
    if cmd in ("live", "l", "today", "scores"):
        state.view = LIVE
        return "live scores"
    if cmd in ("schedule", "sched", "s", "fixtures"):
        if args:
            d = resolve_date(arg, state.schedule_date)
            if d:
                state.schedule_date = d
        state.view = SCHEDULE
        refresher.request_schedule(state.schedule_date)
        return f"schedule {state.schedule_date}"
    if cmd in ("date", "d", "goto"):
        d = resolve_date(arg, state.schedule_date)
        if not d:
            return f"bad date: {arg}"
        state.schedule_date = d
        state.view = SCHEDULE
        refresher.request_schedule(d)
        return f"date -> {d}"
    if cmd in ("groups", "group", "g", "table", "standings"):
        state.view = GROUPS
        if args:
            letter = args[0].upper()
            for i, gp in enumerate(state.standings):
                if gp.name.upper().endswith(letter):
                    state.groups_scroll = i
                    break
        return "group tables"
    if cmd in ("bracket", "b", "knockout", "ko"):
        state.view = BRACKET
        return "bracket"
    if cmd in ("scorers", "scorer", "goals", "boot", "golden"):
        state.view = SCORERS
        state.scorers_tab = 0
        return "top scorers"
    if cmd in ("assists", "assist"):
        state.view = SCORERS
        state.scorers_tab = 1
        return "top assists"
    if cmd in ("team", "t", "nation"):
        if not arg:
            return "usage: :team <name>"
        return open_team(state, arg, refresher)
    if cmd in ("match", "m", "game"):
        if not arg:
            return "usage: :match <event id>"
        state.detail_event_id = args[0]
        state.prev_view = state.view
        state.view = DETAIL
        state.detail_tab = 0
        refresher.request_summary(args[0])
        return f"match {args[0]}"
    if cmd in ("refresh", "r", "reload"):
        refresher.force_all()
        return "refreshing…"
    if cmd in ("help", "h", "?"):
        state.prev_view = state.view if state.view != HELP else state.prev_view
        state.view = HELP
        return "help"
    return f"unknown: {cmd}  (try :help)"


def open_team(state, query, refresher):
    """Find a nation by name/abbr and open a team view."""
    q = query.strip().lower()
    colors = espn.fetch_team_colors()
    match_id = None
    match_name = None
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
    state.team_query = best.get("name")
    state.team_abbr = best.get("abbr")
    state.prev_view = state.view if state.view not in (TEAM,) else state.prev_view
    state.view = TEAM
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
