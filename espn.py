"""
espn.py - ESPN public JSON API client for the FIFA World Cup 2026.

Pure stdlib (urllib). Thread-safe TTL cache. Parses the raw ESPN feeds into
small typed model objects the views consume.

Endpoints used (all unauthenticated, public):
  scoreboard : site.api .../fifa.world/scoreboard?dates=YYYYMMDD[-YYYYMMDD]
  summary    : site.api .../fifa.world/summary?event=ID         (lineups + keyEvents)
  standings  : site.web.api .../v2/.../fifa.world/standings?season=2026  (12 groups)
  teams      : site.api .../fifa.world/teams                     (colors / abbrs)
  leaders    : sports.core.api .../seasons/2026/types/1/leaders  ($ref resolution)
"""

import json
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
WEB = "https://site.web.api.espn.com/apis/v2/sports/soccer/fifa.world"
CORE = "https://sports.core.api.espn.com/v2/sports/soccer/leagues/fifa.world"
SEASON = 2026
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Knockout rounds in order, with the pretty label and the date range to query.
KNOCKOUT_ROUNDS = [
    ("round-of-32", "Round of 32", "20260628-20260703"),
    ("round-of-16", "Round of 16", "20260704-20260708"),
    ("quarterfinals", "Quarterfinals", "20260709-20260713"),
    ("semifinals", "Semifinals", "20260714-20260718"),
    ("3rd-place-match", "3rd Place", "20260718-20260718"),
    ("final", "Final", "20260719-20260719"),
]

ROUND_LABEL = {slug: label for slug, label, _ in KNOCKOUT_ROUNDS}
ROUND_LABEL["group-stage"] = "Group Stage"

# Tournament calendar stages (label, value, start YYYYMMDD, end YYYYMMDD).
STAGES = [
    ("Group Stage", "1", "20260611", "20260627"),
    ("Round of 32", "2", "20260628", "20260703"),
    ("Round of 16", "3", "20260704", "20260708"),
    ("Quarterfinals", "4", "20260709", "20260713"),
    ("Semifinals", "5", "20260714", "20260718"),
    ("3rd Place", "6", "20260718", "20260718"),
    ("Final", "7", "20260719", "20260719"),
]


# ----------------------------------------------------------------------------
# HTTP + cache
# ----------------------------------------------------------------------------

class ApiError(Exception):
    pass


class _Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._store = {}  # url -> (expires_ts, value)

    def get(self, url):
        with self._lock:
            ent = self._store.get(url)
            if ent and ent[0] > time.time():
                return ent[1]
        return None

    def put(self, url, value, ttl):
        with self._lock:
            self._store[url] = (time.time() + ttl, value)

    def clear(self):
        with self._lock:
            self._store.clear()


_cache = _Cache()
# last successful network activity / error, for the status bar
last_ok = [0.0]
last_error = [None]


def get_json(url, ttl=15, force=False):
    if not force:
        cached = _cache.get(url)
        if cached is not None:
            return cached
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        _cache.put(url, data, ttl)
        last_ok[0] = time.time()
        last_error[0] = None
        return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        last_error[0] = str(getattr(e, "reason", e))
        # Fall back to a stale cache entry if we have one.
        stale = _cache.get(url)
        if stale is not None:
            return stale
        raise ApiError(last_error[0])
    except (ValueError, json.JSONDecodeError) as e:
        last_error[0] = "bad json"
        raise ApiError(str(e))


def clear_cache():
    _cache.clear()


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _g(d, *path, default=None):
    """Safe nested get over dicts/lists."""
    cur = d
    for k in path:
        if cur is None:
            return default
        if isinstance(k, int):
            if isinstance(cur, list) and -len(cur) <= k < len(cur):
                cur = cur[k]
            else:
                return default
        else:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
    return cur if cur is not None else default


def parse_iso(s):
    """ESPN ISO like '2026-06-29T20:30Z' -> aware UTC datetime."""
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def to_local(dt):
    if dt is None:
        return None
    return dt.astimezone()


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------

class Competitor:
    def __init__(self, raw):
        team = raw.get("team", {}) or {}
        self.id = str(team.get("id", ""))
        self.abbr = team.get("abbreviation") or team.get("shortDisplayName") or "?"
        self.name = team.get("displayName") or team.get("name") or self.abbr
        self.short_name = team.get("shortDisplayName") or self.name
        self.home_away = raw.get("homeAway", "")
        self.score = raw.get("score")
        self.shootout = raw.get("shootoutScore")
        self.winner = bool(raw.get("winner"))
        self.color = team.get("color")
        self.alt_color = team.get("alternateColor")
        self.logo = team.get("logo")
        self.form = raw.get("form")

    @property
    def score_int(self):
        try:
            return int(self.score)
        except (TypeError, ValueError):
            return None


class Goal:
    def __init__(self, minute, scorer, team_id, own_goal=False, penalty=False):
        self.minute = minute
        self.scorer = scorer
        self.team_id = team_id
        self.own_goal = own_goal
        self.penalty = penalty


# Betting odds ---------------------------------------------------------------
#
# ESPN's public scoreboard/summary feeds embed a sportsbook's odds (DraftKings
# in the US) with no key required. We parse the 3-way moneyline (home/draw/away)
# plus the spread and total, and derive vig-removed implied win probabilities.
# Odds are simply absent for finished games and for fixtures not yet priced —
# so the feature degrades to "nothing shown" with no special-casing.

def parse_american(s):
    """'+115'/'-120'/'EVEN'/225 -> signed int, or None if unparseable."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    t = str(s).strip().upper().replace("−", "-")  # normalize unicode minus
    if t in ("EVEN", "EV", "PK", "PICK"):
        return 100
    try:
        return int(t.replace("+", ""))
    except ValueError:
        return None


def american_to_decimal(a):
    """Signed American odds -> decimal odds (e.g. +115 -> 2.15, -120 -> 1.83)."""
    if a is None:
        return None
    return 1 + (a / 100.0 if a > 0 else 100.0 / abs(a)) if a != 0 else None


def american_to_prob(a):
    """Signed American odds -> raw implied probability (still includes the vig)."""
    if a is None:
        return None
    return 100.0 / (a + 100.0) if a > 0 else abs(a) / (abs(a) + 100.0)


class Odds:
    """Parsed sportsbook odds for one match (moneyline / spread / total)."""

    def __init__(self, raw):
        raw = raw or {}
        self.provider = _g(raw, "provider", "name") or _g(raw, "provider", "displayName") or ""
        self.details = raw.get("details") or ""

        ml = raw.get("moneyline") or {}

        def ml_side(key):
            node = ml.get(key) or {}
            return parse_american(_g(node, "close", "odds") or _g(node, "open", "odds"))

        self.ml_home = ml_side("home")
        self.ml_away = ml_side("away")
        self.ml_draw = ml_side("draw")
        if self.ml_draw is None:  # some feeds carry the draw only under drawOdds
            self.ml_draw = parse_american(_g(raw, "drawOdds", "moneyLine"))

        # total (over/under goals)
        self.over_under = raw.get("overUnder")
        tot = raw.get("total") or {}
        self.over_odds = parse_american(
            _g(tot, "over", "close", "odds") or _g(tot, "over", "open", "odds") or raw.get("overOdds"))
        self.under_odds = parse_american(
            _g(tot, "under", "close", "odds") or _g(tot, "under", "open", "odds") or raw.get("underOdds"))

        # spread (Asian handicap) — home side's line, e.g. '-0.5'
        sp = raw.get("pointSpread") or {}
        self.spread_line = _g(sp, "home", "close", "line") or _g(sp, "home", "open", "line") \
            or raw.get("spread")
        self.spread_odds = parse_american(_g(sp, "home", "close", "odds") or _g(sp, "home", "open", "odds"))

    @property
    def has_moneyline(self):
        return self.ml_home is not None and self.ml_away is not None

    def probabilities(self):
        """Vig-removed (home, draw, away) implied probabilities summing to 1.0.

        Returns None if the moneyline is incomplete. A missing draw price
        (two-way market) contributes 0 and the remaining two are normalized.
        """
        if not self.has_moneyline:
            return None
        raws = [american_to_prob(self.ml_home) or 0.0,
                american_to_prob(self.ml_draw) or 0.0,
                american_to_prob(self.ml_away) or 0.0]
        total = sum(raws)
        if total <= 0:
            return None
        return tuple(x / total for x in raws)


def _parse_odds(odds_list):
    """First entry with a usable moneyline from an ESPN odds/pickcenter list."""
    for o in (odds_list or []):
        if not o:
            continue
        od = Odds(o)
        if od.has_moneyline:
            return od
    return None


class Match:
    def __init__(self, raw):
        self.id = str(raw.get("id", ""))
        self.name = raw.get("name", "")
        self.short_name = raw.get("shortName", "")
        self.date = parse_iso(raw.get("date"))
        comp = _g(raw, "competitions", 0, default={}) or {}
        self.comp = comp
        status = raw.get("status") or comp.get("status") or {}
        stype = status.get("type", {}) or {}
        self.state = stype.get("state", "pre")          # pre | in | post
        self.status_name = stype.get("name", "")
        self.detail = stype.get("shortDetail") or stype.get("detail") or ""
        self.completed = bool(stype.get("completed"))
        self.clock = status.get("displayClock", "")
        self.period = status.get("period", 0)
        self.season_slug = _g(raw, "season", "slug", default="")
        self.venue = _g(comp, "venue", "fullName", default="")
        self.venue_city = _g(comp, "venue", "address", "city", default="")
        # competitors
        comps = comp.get("competitors", []) or []
        self.home = None
        self.away = None
        self.competitors = [Competitor(c) for c in comps]
        for c in self.competitors:
            if c.home_away == "home":
                self.home = c
            elif c.home_away == "away":
                self.away = c
        if self.home is None and len(self.competitors) > 0:
            self.home = self.competitors[0]
        if self.away is None and len(self.competitors) > 1:
            self.away = self.competitors[1]
        # inline goals from competition.details (present once a match starts)
        self.goals = self._parse_detail_goals(comp.get("details", []) or [])
        self.notes = [n.get("text", "") for n in (comp.get("notes", []) or [])]
        self.headline = _g(comp, "headlines", 0, "description", default="")
        # embedded sportsbook odds (present pre-match; absent once played)
        self.odds = _parse_odds(comp.get("odds"))

    def _parse_detail_goals(self, details):
        goals = []
        for d in details:
            if not d.get("scoringPlay"):
                continue
            if d.get("shootout"):
                continue
            minute = _g(d, "clock", "displayValue", default="")
            ath = _g(d, "athletesInvolved", 0, "displayName") or \
                _g(d, "participants", 0, "athlete", "displayName") or "?"
            tid = str(_g(d, "team", "id", default=""))
            goals.append(Goal(minute, ath, tid,
                              own_goal=bool(d.get("ownGoal")),
                              penalty=bool(d.get("penaltyKick"))))
        return goals

    @property
    def is_live(self):
        return self.state == "in"

    @property
    def is_pre(self):
        return self.state == "pre"

    @property
    def is_post(self):
        return self.state == "post"

    @property
    def has_shootout(self):
        return self.status_name == "STATUS_FINAL_PEN" or (
            self.home and self.home.shootout is not None)

    def signature(self):
        """A value that changes when the visible state changes (for goal flash)."""
        h = self.home.score if self.home else "?"
        a = self.away.score if self.away else "?"
        return f"{self.id}:{h}:{a}:{self.state}:{self.clock}"


class GroupRow:
    def __init__(self, entry):
        team = entry.get("team", {}) or {}
        self.id = str(team.get("id", ""))
        self.name = team.get("displayName") or team.get("name") or "?"
        self.abbr = team.get("abbreviation") or self.name[:3].upper()
        stats = {s.get("name"): s for s in entry.get("stats", []) or []}

        def val(name, default=0):
            s = stats.get(name)
            if not s:
                return default
            v = s.get("value")
            if v is None:
                try:
                    return int(s.get("displayValue", default))
                except (TypeError, ValueError):
                    return default
            return int(v)

        def disp(name, default=""):
            s = stats.get(name)
            return s.get("displayValue", default) if s else default

        self.gp = val("gamesPlayed")
        self.w = val("wins")
        self.d = val("ties")
        self.l = val("losses")
        self.gf = val("pointsFor")
        self.ga = val("pointsAgainst")
        self.gd_disp = disp("pointDifferential", str(self.gf - self.ga))
        self.gd = val("pointDifferential", self.gf - self.ga)
        self.pts = val("points")
        note = entry.get("note") or {}
        self.rank = note.get("rank") or val("rank", 0)
        self.qual_color = note.get("color")
        self.qual_desc = note.get("description", "")


class Group:
    def __init__(self, child):
        self.name = child.get("name") or child.get("abbreviation") or "Group"
        entries = _g(child, "standings", "entries", default=[]) or []
        self.rows = [GroupRow(e) for e in entries]
        self.rows.sort(key=lambda r: (r.rank if r.rank else 99))


# ----------------------------------------------------------------------------
# Public fetch functions (return models)
# ----------------------------------------------------------------------------

def fetch_matches(dates=None, ttl=15, force=False):
    url = f"{SITE}/scoreboard"
    if dates:
        url += f"?dates={dates}"
    data = get_json(url, ttl=ttl, force=force)
    events = data.get("events", []) or []
    matches = [Match(e) for e in events]
    matches.sort(key=lambda m: (m.date or datetime.max.replace(tzinfo=timezone.utc)))
    label = _g(data, "leagues", 0, "season", "type", "name", default="")
    return matches, label


def fetch_standings(ttl=120, force=False):
    url = f"{WEB}/standings?season={SEASON}"
    data = get_json(url, ttl=ttl, force=force)
    children = data.get("children", []) or []
    groups = [Group(c) for c in children]
    return groups


def fetch_bracket(ttl=60, force=False):
    """One scoreboard call across the whole knockout span, grouped by round."""
    url = f"{SITE}/scoreboard?dates=20260628-20260720"
    data = get_json(url, ttl=ttl, force=force)
    events = data.get("events", []) or []
    rounds = {slug: [] for slug, _, _ in KNOCKOUT_ROUNDS}
    for e in events:
        m = Match(e)
        if m.season_slug in rounds:
            rounds[m.season_slug].append(m)
    for slug in rounds:
        rounds[slug].sort(key=lambda m: (m.date or datetime.max.replace(tzinfo=timezone.utc)))
    return rounds


def _resolve_ref(ref):
    if not ref:
        return {}
    ref = ref.replace("http://", "https://")
    try:
        return get_json(ref, ttl=3600)
    except ApiError:
        return {}


def fetch_scorers(limit=20, ttl=300, force=False):
    """Top scorers + assists. Resolves athlete/team $refs (cached, threaded)."""
    url = f"{CORE}/seasons/{SEASON}/types/1/leaders?lang=en&region=us"
    data = get_json(url, ttl=ttl, force=force)
    cats = {c.get("name"): c for c in data.get("categories", []) or []}

    def build(cat_name):
        cat = cats.get(cat_name)
        if not cat:
            return []
        leaders = (cat.get("leaders") or [])[:limit]
        # Resolve refs concurrently.
        results = [None] * len(leaders)

        def work(i, ld):
            ath = _resolve_ref(_g(ld, "athlete", "$ref"))
            tm = _resolve_ref(_g(ld, "team", "$ref"))
            results[i] = {
                "value": int(ld.get("value", 0)),
                "name": ath.get("displayName") or ath.get("fullName") or "?",
                "team": tm.get("displayName") or "?",
                "team_abbr": tm.get("abbreviation") or "",
                "team_id": str(tm.get("id", "")),
                "display": ld.get("displayValue", ""),
            }

        threads = []
        for i, ld in enumerate(leaders):
            t = threading.Thread(target=work, args=(i, ld), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=12)
        return [r for r in results if r]

    return {
        "goals": build("goalsLeaders"),
        "assists": build("assistsLeaders"),
    }


# Match-summary models -------------------------------------------------------

class RosterPlayer:
    def __init__(self, raw):
        ath = raw.get("athlete", {}) or {}
        self.name = ath.get("displayName") or "?"
        self.short = ath.get("shortName") or self.name
        self.jersey = raw.get("jersey", "")
        self.pos = _g(raw, "position", "abbreviation", default="")
        self.pos_name = _g(raw, "position", "name", default="")
        self.starter = bool(raw.get("starter"))
        self.subbed_in = bool(raw.get("subbedIn"))
        self.subbed_out = bool(raw.get("subbedOut"))
        self.formation_place = raw.get("formationPlace")


class TeamLineup:
    def __init__(self, raw):
        self.team_id = str(_g(raw, "team", "id", default=""))
        self.name = _g(raw, "team", "displayName", default="?")
        self.abbr = _g(raw, "team", "abbreviation", default="")
        self.home_away = raw.get("homeAway", "")
        self.formation = raw.get("formation") or ""
        players = raw.get("roster", []) or []
        self.players = [RosterPlayer(p) for p in players]
        self.starters = [p for p in self.players if p.starter]
        self.bench = [p for p in self.players if not p.starter]


class KeyEvent:
    def __init__(self, raw):
        self.type = _g(raw, "type", "text", default="")
        self.type_key = _g(raw, "type", "type", default="")
        self.scoring = bool(raw.get("scoringPlay"))
        self.minute = _g(raw, "clock", "displayValue", default="")
        self.period = _g(raw, "period", "number", default=0)
        self.team_id = str(_g(raw, "team", "id", default=""))
        self.team = _g(raw, "team", "displayName", default="")
        parts = raw.get("participants", []) or []
        self.players = [_g(p, "athlete", "displayName") for p in parts if _g(p, "athlete", "displayName")]
        self.text = raw.get("text", "")
        self.short = raw.get("shortText", "")


class MatchDetail:
    def __init__(self, raw):
        self.lineups = [TeamLineup(r) for r in (raw.get("rosters", []) or [])]
        self.key_events = [KeyEvent(k) for k in (raw.get("keyEvents", []) or [])]
        self.boxscore_teams = raw.get("boxscore", {}).get("teams", []) or []
        self.venue = _g(raw, "gameInfo", "venue", "fullName", default="")
        attendance = _g(raw, "gameInfo", "attendance")
        self.attendance = attendance
        self.commentary = raw.get("commentary", []) or []
        # odds live under pickcenter (richer) or a top-level odds list
        self.odds = _parse_odds(raw.get("pickcenter")) or _parse_odds(raw.get("odds"))
        # A lightweight Match parsed from the summary header, used when the
        # match wasn't already loaded from a scoreboard list.
        self.header_match = None
        hdr = raw.get("header")
        if hdr and _g(hdr, "competitions", 0, "competitors"):
            try:
                self.header_match = Match(hdr)
            except Exception:
                self.header_match = None

    def team_stats(self):
        """-> list of (label, away_value, home_value) aligned by stat name."""
        if len(self.boxscore_teams) < 2:
            return []
        def smap(team):
            return {s.get("name"): (s.get("label", s.get("name")), s.get("displayValue", ""))
                    for s in team.get("statistics", []) or []}
        t0 = self.boxscore_teams[0]
        t1 = self.boxscore_teams[1]
        m0, m1 = smap(t0), smap(t1)
        # boxscore order: figure out which is home/away
        ha0 = t0.get("homeAway")
        keys = ["possessionPct", "totalShots", "shotsOnTarget", "wonCorners",
                "foulsCommitted", "yellowCards", "redCards", "offsides", "saves"]
        rows = []
        for k in keys:
            if k in m0 or k in m1:
                label = (m0.get(k) or m1.get(k))[0]
                v0 = m0.get(k, ("", "—"))[1]
                v1 = m1.get(k, ("", "—"))[1]
                if ha0 == "home":
                    rows.append((label, v1, v0))  # (label, away, home)
                else:
                    rows.append((label, v0, v1))
        return rows


def fetch_summary(event_id, ttl=20, force=False):
    url = f"{SITE}/summary?event={event_id}"
    data = get_json(url, ttl=ttl, force=force)
    return MatchDetail(data)


# Team colors ----------------------------------------------------------------

_team_colors = {}
_team_colors_loaded = [False]


def fetch_team_colors(force=False):
    """Map team id/abbr -> {'color','alt','name'} for consistent coloring."""
    if _team_colors_loaded[0] and not force:
        return _team_colors
    try:
        data = get_json(f"{SITE}/teams", ttl=86400, force=force)
    except ApiError:
        return _team_colors
    teams = _g(data, "sports", 0, "leagues", 0, "teams", default=[]) or []
    for t in teams:
        team = t.get("team", {}) or {}
        rec = {
            "color": team.get("color"),
            "alt": team.get("alternateColor"),
            "name": team.get("displayName"),
            "abbr": team.get("abbreviation"),
        }
        _team_colors[str(team.get("id"))] = rec
        if team.get("abbreviation"):
            _team_colors[team["abbreviation"]] = rec
    _team_colors_loaded[0] = True
    return _team_colors


def team_color(tid=None, abbr=None, fallback="888888"):
    rec = _team_colors.get(str(tid)) or _team_colors.get(abbr)
    if rec and rec.get("color") and rec["color"].upper() not in ("FFFFFF", "000000"):
        return rec["color"]
    return fallback
