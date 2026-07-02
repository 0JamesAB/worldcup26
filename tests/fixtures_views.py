"""
fixtures_views.py - Synthetic, fully offline AppState fixtures for goldens.

Fabricates raw ESPN-shaped dicts and feeds them through the real espn model
classes (Match / Competitor / Odds / Group / MatchDetail) so the rendering
code paths are authentic. No network is ever touched: team colors are
injected straight into espn's module-level cache and every fetch-derived
field is pre-populated on the AppState.

Determinism contract (freeze_environment):
  - TZ pinned to UTC (espn.to_local / strftime are TZ-dependent)
  - color depth pinned to truecolor (env detection happens at import)
  - WCUP_ODDS / WCUP_ODDS_FORMAT cleared (odds default on, American)
  - theme installed exactly as wc.py does: set_theme(WorldCupTheme)
  - espn.last_error cleared (statusline "reconnecting" chip)
  - every state carries a live match so footer_right never calls now()
  - st.frame set to FRAME; render() increments it, so tests must re-set
    st.frame = FRAME before each render call
"""

import os
import time

import espn
import state as S
from palette import WorldCupTheme
from tui import term
from tui.theme import set_theme

FRAME = 41  # render() bumps this to 42 -> live pulse phase is "on"

# 32 nations: (abbr, name, hex color). Colors avoid FFFFFF/000000, which
# espn.team_color rejects.
TEAMS = [
    ("BRA", "Brazil", "f7dc11"), ("ARG", "Argentina", "6bb2e2"),
    ("FRA", "France", "1f3b73"), ("ENG", "England", "d43333"),
    ("ESP", "Spain", "c60b1e"), ("GER", "Germany", "3d4d57"),
    ("POR", "Portugal", "046a38"), ("NED", "Netherlands", "f36c21"),
    ("USA", "United States", "1f2f86"), ("MEX", "Mexico", "006847"),
    ("CAN", "Canada", "d52b1e"), ("JPN", "Japan", "192f60"),
    ("KOR", "South Korea", "cd2e3a"), ("MAR", "Morocco", "c1272d"),
    ("CRO", "Croatia", "ed1c24"), ("URU", "Uruguay", "5cbfeb"),
    ("BEL", "Belgium", "e30613"), ("ITA", "Italy", "0066b2"),
    ("COL", "Colombia", "fcd116"), ("SEN", "Senegal", "00853f"),
    ("GHA", "Ghana", "ce1126"), ("AUS", "Australia", "ffb81c"),
    ("SUI", "Switzerland", "da291c"), ("DEN", "Denmark", "c8102e"),
    ("POL", "Poland", "dc143c"), ("AUT", "Austria", "ed2939"),
    ("ECU", "Ecuador", "ffdd00"), ("NGA", "Nigeria", "008751"),
    ("EGY", "Egypt", "b8860b"), ("IRN", "Iran", "239f40"),
    ("KSA", "Saudi Arabia", "165d31"), ("QAT", "Qatar", "8a1538"),
]


def _tid(i):
    return str(201 + i)


def install_team_colors():
    """Inject a fixed team-color map into espn's cache (no network)."""
    espn._team_colors.clear()
    for i, (abbr, name, color) in enumerate(TEAMS):
        rec = {"color": color, "alt": "222222", "name": name, "abbr": abbr}
        espn._team_colors[_tid(i)] = rec
        espn._team_colors[abbr] = rec
    espn._team_colors_loaded[0] = True


def freeze_environment():
    """Pin every global the renderer reads so frames are byte-stable."""
    os.environ["TZ"] = "UTC"
    time.tzset()
    os.environ.pop("WCUP_ODDS", None)
    os.environ.pop("WCUP_ODDS_FORMAT", None)
    term.set_color_depth("truecolor")
    set_theme(WorldCupTheme)
    espn.last_error[0] = None
    install_team_colors()


# ----------------------------------------------------------------------------
# raw ESPN-shaped dict builders
# ----------------------------------------------------------------------------

def _team_raw(i):
    abbr, name, color = TEAMS[i]
    return {"id": _tid(i), "abbreviation": abbr, "displayName": name,
            "shortDisplayName": name, "color": color, "alternateColor": "222222"}


def _comp_raw(team, homeaway, score=None, winner=False, shootout=None, form=None):
    d = {"team": team, "homeAway": homeaway, "winner": winner}
    if score is not None:
        d["score"] = score
    if shootout is not None:
        d["shootoutScore"] = shootout
    if form is not None:
        d["form"] = form
    return d


def _placeholder_raw(label, homeaway):
    return {"team": {"id": "", "abbreviation": "TBD", "displayName": label,
                     "shortDisplayName": label}, "homeAway": homeaway}


def _goal_raw(minute, scorer, tid, og=False, pen=False):
    return {"scoringPlay": True, "clock": {"displayValue": minute},
            "athletesInvolved": [{"displayName": scorer}],
            "team": {"id": tid}, "ownGoal": og, "penaltyKick": pen}


def _odds_raw(home_ml, draw_ml, away_ml):
    return {
        "provider": {"name": "DraftKings"},
        "details": "spread",
        "moneyline": {
            "home": {"close": {"odds": home_ml}},
            "away": {"close": {"odds": away_ml}},
            "draw": {"close": {"odds": draw_ml}},
        },
        "overUnder": 2.5,
        "total": {"over": {"close": {"odds": "-110"}},
                  "under": {"close": {"odds": "-105"}}},
        "pointSpread": {"home": {"close": {"line": "-0.5", "odds": "-115"}}},
    }


def _match_raw(mid, date, slug, home, away, state, status_name,
               clock="", period=0, completed=False, detail="", venue="",
               details=None, odds=None):
    return {
        "id": mid,
        "name": "",
        "shortName": "",
        "date": date,
        "season": {"slug": slug},
        "status": {
            "type": {"state": state, "name": status_name,
                     "shortDetail": detail, "completed": completed},
            "displayClock": clock,
            "period": period,
        },
        "competitions": [{
            "venue": {"fullName": venue, "address": {"city": ""}},
            "competitors": [home, away],
            "details": details or [],
            "odds": [odds] if odds else [],
        }],
    }


# ----------------------------------------------------------------------------
# today's scoreboard (shared by every fixture: header live count + footer)
# ----------------------------------------------------------------------------

def _today_matches():
    # post, 12:00: shootout win for the away side
    m_pens = espn.Match(_match_raw(
        "9004", "2026-06-15T12:00Z", "group-stage",
        _comp_raw(_team_raw(6), "home", score="1", shootout=3),
        _comp_raw(_team_raw(7), "away", score="1", shootout=4, winner=True),
        "post", "STATUS_FINAL_PEN", period=5, completed=True,
        venue="Gillette Stadium"))
    # post, 13:00: plain FT with scorers
    m_ft = espn.Match(_match_raw(
        "9005", "2026-06-15T13:00Z", "group-stage",
        _comp_raw(_team_raw(8), "home", score="3", winner=True),
        _comp_raw(_team_raw(9), "away", score="0"),
        "post", "STATUS_FULL_TIME", period=2, completed=True,
        venue="AT&T Stadium",
        details=[_goal_raw("11'", "Tyler Reyes", _tid(8)),
                 _goal_raw("49'", "Gio Marsh", _tid(8)),
                 _goal_raw("88'", "Alex Boyd", _tid(8), pen=True)]))
    # live, 16:00: 63' with a penalty and an own goal on the sheet
    m_live = espn.Match(_match_raw(
        "9001", "2026-06-15T16:00Z", "group-stage",
        _comp_raw(_team_raw(0), "home", score="2"),
        _comp_raw(_team_raw(1), "away", score="1"),
        "in", "STATUS_IN_PROGRESS", clock="63'", period=2,
        venue="MetLife Stadium",
        details=[_goal_raw("12'", "Julian Reyes", _tid(1), pen=True),
                 _goal_raw("34'", "Marcos Silva", _tid(0)),
                 _goal_raw("58'", "Nico Ortega", _tid(0), og=True)]))
    # live, 16:30: goalless at half time
    m_ht = espn.Match(_match_raw(
        "9002", "2026-06-15T16:30Z", "group-stage",
        _comp_raw(_team_raw(2), "home", score="0"),
        _comp_raw(_team_raw(3), "away", score="0"),
        "in", "STATUS_HALFTIME", clock="45'+2", period=2,
        venue="Lumen Field"))
    # pre, 20:00: priced-up fixture (odds bars) with recent form
    m_pre = espn.Match(_match_raw(
        "9003", "2026-06-15T20:00Z", "group-stage",
        _comp_raw(_team_raw(4), "home", form="WWDWL"),
        _comp_raw(_team_raw(5), "away", form="LWDWW"),
        "pre", "STATUS_SCHEDULED", detail="6/15 - 8:00 PM",
        odds=_odds_raw("-135", "+260", "+380")))
    return [m_pens, m_ft, m_live, m_ht, m_pre]


def _base_state(view):
    freeze_environment()
    st = S.AppState()
    st.view = view
    st.frame = FRAME
    st.status = "updated 12:00:00"
    st.toasts = []
    st.matches_today = _today_matches()
    st.today_label = "Group Stage"
    for m in st.matches_today:
        st.match_index[m.id] = m
    return st


# ----------------------------------------------------------------------------
# live
# ----------------------------------------------------------------------------

def state_live():
    st = _base_state(S.LIVE)
    st.live_sel = 0
    t = S.Toast("⚽ GOAL!  ARG 1 - 2 BRA", kind="goal", ttl=1e12)
    t.born = 0.0  # age > 1.2 forever: alive, never in the flash window
    st.toasts = [t]
    return st


def state_live_palette():
    st = _base_state(S.LIVE)
    st.command_mode = True
    st.command_buf = "gr"
    st.command_sel = 0
    return st


# ----------------------------------------------------------------------------
# schedule
# ----------------------------------------------------------------------------

def state_schedule():
    st = _base_state(S.SCHEDULE)
    st.schedule_date = "20260615"
    st.schedule_label = "Group Stage"
    st.sched_sel = 2
    m_aet = espn.Match(_match_raw(
        "9006", "2026-06-15T14:30Z", "group-stage",
        _comp_raw(_team_raw(10), "home", score="2", winner=True),
        _comp_raw(_team_raw(11), "away", score="1"),
        "post", "STATUS_FINAL_AET", period=4, completed=True,
        venue="BMO Field"))
    m_pre1 = espn.Match(_match_raw(
        "9007", "2026-06-15T18:00Z", "group-stage",
        _comp_raw(_team_raw(12), "home"),
        _comp_raw(_team_raw(13), "away"),
        "pre", "STATUS_SCHEDULED", venue="Levi's Stadium"))
    m_pre2 = espn.Match(_match_raw(
        "9008", "2026-06-15T22:00Z", "group-stage",
        _comp_raw(_team_raw(14), "home"),
        _comp_raw(_team_raw(15), "away"),
        "pre", "STATUS_SCHEDULED", venue="Estadio Azteca"))
    today = {m.id: m for m in st.matches_today}
    st.schedule_matches = [today["9004"], today["9005"], m_aet, today["9001"],
                           today["9002"], m_pre1, today["9003"], m_pre2]
    for m in st.schedule_matches:
        st.match_index[m.id] = m
    return st


# ----------------------------------------------------------------------------
# groups
# ----------------------------------------------------------------------------

def _entry_raw(team_i, rank, gp, w, d, l, gf, ga, note=None):
    gd = gf - ga
    stats = [
        {"name": "gamesPlayed", "value": gp}, {"name": "wins", "value": w},
        {"name": "ties", "value": d}, {"name": "losses", "value": l},
        {"name": "pointsFor", "value": gf}, {"name": "pointsAgainst", "value": ga},
        {"name": "pointDifferential", "value": gd,
         "displayValue": ("+" if gd > 0 else "") + str(gd)},
        {"name": "points", "value": 3 * w + d}, {"name": "rank", "value": rank},
    ]
    entry = {"team": _team_raw(team_i), "stats": stats}
    if note is not None:
        entry["note"] = {"rank": rank, "color": note[0], "description": note[1]}
    return entry


def state_groups():
    freeze = [("#4ade80", "advance"), ("#4ade80", "advance"),
              ("#f0c458", "best third"), None]
    plain = [None, None, None, None]
    stats = [(3, 3, 0, 0, 7, 1), (3, 1, 2, 0, 4, 2),
             (3, 1, 1, 1, 3, 4), (3, 0, 1, 2, 1, 8)]

    def group(letter, base, notes):
        entries = [_entry_raw(base + k, k + 1, *stats[k], note=notes[k])
                   for k in range(4)]
        return espn.Group({"name": "Group " + letter,
                           "standings": {"entries": entries}})

    st = _base_state(S.GROUPS)
    st.standings = [group("A", 0, freeze), group("B", 4, freeze),
                    group("C", 8, plain), group("D", 12, freeze)]
    st.groups_scroll = 0
    return st


# ----------------------------------------------------------------------------
# bracket
# ----------------------------------------------------------------------------

def _bracket():
    rounds = {slug: [] for slug, _, _ in espn.KNOCKOUT_ROUNDS}
    # Round of 32: matches 1-8 played (match 4 on pens), 9-16 scheduled.
    for i in range(16):
        date = "2026-06-%02dT%02d:00Z" % (28 + i // 6, 10 + (i % 6) * 2)
        mid = str(8101 + i)
        hi, ai = 2 * i, 2 * i + 1
        if i < 8:
            if i == 3:
                home = _comp_raw(_team_raw(hi), "home", score="1", shootout=3)
                away = _comp_raw(_team_raw(ai), "away", score="1", shootout=4,
                                 winner=True)
                status = "STATUS_FINAL_PEN"
            elif i % 2 == 0:
                home = _comp_raw(_team_raw(hi), "home", score="2", winner=True)
                away = _comp_raw(_team_raw(ai), "away", score="1")
                status = "STATUS_FULL_TIME"
            else:
                home = _comp_raw(_team_raw(hi), "home", score="1")
                away = _comp_raw(_team_raw(ai), "away", score="2", winner=True)
                status = "STATUS_FULL_TIME"
            m = _match_raw(mid, date, "round-of-32", home, away,
                           "post", status, period=2, completed=True)
        else:
            m = _match_raw(mid, date, "round-of-32",
                           _comp_raw(_team_raw(hi), "home"),
                           _comp_raw(_team_raw(ai), "away"),
                           "pre", "STATUS_SCHEDULED")
        rounds["round-of-32"].append(espn.Match(m))

    # Round of 16: slot 1 live and slot 2 scheduled with the decided teams;
    # the rest still carry "Round of 32 N Winner" placeholders.
    for j in range(8):
        date = "2026-07-%02dT%02d:00Z" % (4 + j // 4, 12 + (j % 4) * 3)
        mid = str(8201 + j)
        if j == 0:
            m = _match_raw(mid, date, "round-of-16",
                           _comp_raw(_team_raw(3), "home", score="1"),
                           _comp_raw(_team_raw(0), "away", score="1"),
                           "in", "STATUS_IN_PROGRESS", clock="71'", period=2)
        elif j == 1:
            m = _match_raw(mid, date, "round-of-16",
                           _comp_raw(_team_raw(7), "home"),
                           _comp_raw(_team_raw(4), "away"),
                           "pre", "STATUS_SCHEDULED")
        else:
            m = _match_raw(mid, date, "round-of-16",
                           _placeholder_raw("Round of 32 %d Winner" % (2 * j + 2), "home"),
                           _placeholder_raw("Round of 32 %d Winner" % (2 * j + 1), "away"),
                           "pre", "STATUS_SCHEDULED")
        rounds["round-of-16"].append(espn.Match(m))

    def placeholder_round(slug, n, prev_label, mid0, day0):
        for k in range(n):
            date = "2026-07-%02dT%02d:00Z" % (day0 + k // 2, 15 + (k % 2) * 3)
            m = _match_raw(str(mid0 + k), date, slug,
                           _placeholder_raw("%s %d Winner" % (prev_label, 2 * k + 2), "home"),
                           _placeholder_raw("%s %d Winner" % (prev_label, 2 * k + 1), "away"),
                           "pre", "STATUS_SCHEDULED")
            rounds[slug].append(espn.Match(m))

    placeholder_round("quarterfinals", 4, "Round of 16", 8301, 9)
    placeholder_round("semifinals", 2, "Quarterfinal", 8401, 14)
    rounds["final"].append(espn.Match(_match_raw(
        "8501", "2026-07-19T19:00Z", "final",
        _placeholder_raw("Semifinal 2 Winner", "home"),
        _placeholder_raw("Semifinal 1 Winner", "away"),
        "pre", "STATUS_SCHEDULED", venue="MetLife Stadium")))
    rounds["3rd-place-match"].append(espn.Match(_match_raw(
        "8502", "2026-07-18T19:00Z", "3rd-place-match",
        _placeholder_raw("Semifinal 2 Loser", "home"),
        _placeholder_raw("Semifinal 1 Loser", "away"),
        "pre", "STATUS_SCHEDULED")))
    return rounds


def state_bracket():
    st = _base_state(S.BRACKET)
    st.bracket = _bracket()
    for ms in st.bracket.values():
        for m in ms:
            st.match_index[m.id] = m
    return st


def state_bracket_scrolled():
    st = state_bracket()
    st.bracket_scroll_y = 24
    st.bracket_scroll_x = 30
    return st


# ----------------------------------------------------------------------------
# scorers
# ----------------------------------------------------------------------------

_GOALS = [
    (7, "Marcos Silva", 0), (6, "Leo Duret", 2), (5, "Harry Cole", 3),
    (5, "Julian Reyes", 1), (4, "Alvaro Marin", 4), (4, "Ade Okafor", 19),
    (3, "Tomas Vlk", 14), (3, "Kenji Sato", 11), (2, "Luca Bruno", 17),
    (2, "Mo Salif", 28),
]

_ASSISTS = [
    (5, "Pedro Lima", 0), (4, "Theo Marchand", 2), (4, "Jack Rowe", 3),
    (3, "Iker Soler", 4), (3, "Daan Visser", 7), (2, "Mateo Cruz", 1),
    (2, "Yuto Mori", 11), (2, "Omar Farouk", 28), (1, "Nils Berg", 23),
]


def _scorer_rows(spec):
    return [{"value": v, "name": n, "team": TEAMS[i][1],
             "team_abbr": TEAMS[i][0], "team_id": _tid(i), "display": str(v)}
            for v, n, i in spec]


def _scorers_state(tab, sel):
    st = _base_state(S.SCORERS)
    st.scorers = {"goals": _scorer_rows(_GOALS),
                  "assists": _scorer_rows(_ASSISTS)}
    st.scorers_tab = tab
    st.scorers_sel = sel
    return st


def state_scorers_goals():
    return _scorers_state(0, 0)


def state_scorers_assists():
    return _scorers_state(1, 3)


# ----------------------------------------------------------------------------
# match detail
# ----------------------------------------------------------------------------

_ENG_XI = [
    ("1", "Pickford", "G"), ("2", "Walker", "D"), ("5", "Stones", "D"),
    ("6", "Maguire", "D"), ("3", "Shaw", "D"), ("4", "Rice", "M"),
    ("10", "Bellingham", "M"), ("8", "Foden", "M"), ("7", "Saka", "F"),
    ("9", "Kane", "F"), ("11", "Rashford", "F"),
]

_FRA_XI = [
    ("1", "Maignan", "G"), ("2", "Kounde", "D"), ("4", "Varane", "D"),
    ("5", "Upamecano", "D"), ("22", "Hernandez", "D"), ("7", "Griezmann", "M"),
    ("8", "Tchouameni", "M"), ("6", "Camavinga", "M"), ("11", "Dembele", "M"),
    ("10", "Mbappe", "F"), ("9", "Giroud", "F"),
]


def _player_raw(jersey, name, pos, place, starter=True):
    p = {"athlete": {"displayName": name, "shortName": name},
         "jersey": jersey,
         "position": {"abbreviation": pos, "name": pos},
         "starter": starter, "subbedIn": False, "subbedOut": False}
    if place is not None:
        p["formationPlace"] = str(place)
    return p


def _lineup_raw(team_i, homeaway, formation, xi, bench):
    roster = [_player_raw(j, n, p, place)
              for place, (j, n, p) in enumerate(xi, start=1)]
    roster += [_player_raw(j, n, p, None, starter=False) for j, n, p in bench]
    return {"team": {"id": _tid(team_i), "displayName": TEAMS[team_i][1],
                     "abbreviation": TEAMS[team_i][0]},
            "homeAway": homeaway, "formation": formation, "roster": roster}


def _event_raw(type_text, minute, team_i, players, scoring=False, period=1):
    return {"type": {"text": type_text, "type": type_text.lower()},
            "scoringPlay": scoring,
            "clock": {"displayValue": minute},
            "period": {"number": period},
            "team": {"id": _tid(team_i), "displayName": TEAMS[team_i][1]},
            "participants": [{"athlete": {"displayName": p}} for p in players],
            "text": "", "shortText": ""}


_STATS = [
    ("possessionPct", "Possession", "45%", "55%"),
    ("totalShots", "Shots", "9", "14"),
    ("shotsOnTarget", "Shots on Target", "3", "6"),
    ("wonCorners", "Corner Kicks", "4", "7"),
    ("foulsCommitted", "Fouls", "13", "10"),
    ("yellowCards", "Yellow Cards", "2", "1"),
    ("redCards", "Red Cards", "1", "0"),
    ("offsides", "Offsides", "1", "2"),
    ("saves", "Saves", "2", "4"),
]


def _summary_raw():
    def boxteam(homeaway, col):
        return {"homeAway": homeaway,
                "statistics": [{"name": n, "label": lbl,
                                "displayValue": (av, hv)[col]}
                               for n, lbl, av, hv in _STATS]}
    return {
        "rosters": [_lineup_raw(3, "home", "4-3-3", _ENG_XI,
                                [("12", "Henderson", "M"), ("15", "Watkins", "F")]),
                    _lineup_raw(2, "away", "4-4-2", _FRA_XI,
                                [("13", "Fofana", "M"), ("14", "Thuram", "F")])],
        "keyEvents": [
            _event_raw("Goal", "23'", 3, ["Harry Kane"], scoring=True),
            _event_raw("Yellow Card", "31'", 2, ["Aurelien Tchouameni"]),
            _event_raw("Goal", "44'", 2, ["Kylian Mbappe"], scoring=True),
            _event_raw("Substitution", "58'", 3,
                       ["Marcus Rashford", "Bukayo Saka"], period=2),
            _event_raw("Red Card", "63'", 2, ["Dayot Upamecano"], period=2),
            _event_raw("Penalty - Scored", "77'", 3, ["Phil Foden"],
                       scoring=True, period=2),
            _event_raw("Substitution", "84'", 2,
                       ["Olivier Giroud", "Ousmane Dembele"], period=2),
        ],
        "boxscore": {"teams": [boxteam("away", 0), boxteam("home", 1)]},
        "gameInfo": {"venue": {"fullName": "SoFi Stadium"},
                     "attendance": 71000},
    }


def _detail_match():
    return espn.Match(_match_raw(
        "9101", "2026-07-10T16:00Z", "quarterfinals",
        _comp_raw(_team_raw(3), "home", score="2", winner=True),
        _comp_raw(_team_raw(2), "away", score="1"),
        "post", "STATUS_FULL_TIME", period=2, completed=True,
        venue="SoFi Stadium"))


def _detail_state(tab):
    st = _base_state(S.DETAIL)
    m = _detail_match()
    st.match_index[m.id] = m
    st.detail_event_id = m.id
    st.detail_tab = tab
    st.detail_scroll = 0
    st.summaries[m.id] = espn.MatchDetail(_summary_raw())
    return st


def state_detail_lineups():
    return _detail_state(0)


def state_detail_timeline():
    return _detail_state(1)


def state_detail_stats():
    return _detail_state(2)


def state_detail_odds():
    """Pre-match centre: odds strip in the header + full odds panel body."""
    st = _base_state(S.DETAIL)
    st.detail_event_id = "9003"  # today's priced-up pre-match fixture
    st.detail_tab = 0
    st.summaries["9003"] = espn.MatchDetail({
        "pickcenter": [_odds_raw("-135", "+260", "+380")],
        "gameInfo": {"venue": {"fullName": "Estadio Akron"}},
    })
    return st


# ----------------------------------------------------------------------------
# team / help
# ----------------------------------------------------------------------------

def state_team():
    st = _base_state(S.TEAM)
    st.team_query = "Brazil"
    st.team_abbr = "BRA"
    st.sched_sel = 1
    st.team_matches = [
        espn.Match(_match_raw(
            "9201", "2026-06-12T18:00Z", "group-stage",
            _comp_raw(_team_raw(0), "home", score="2", winner=True),
            _comp_raw(_team_raw(22), "away", score="0"),
            "post", "STATUS_FULL_TIME", period=2, completed=True,
            venue="MetLife Stadium")),
        espn.Match(_match_raw(
            "9202", "2026-06-16T18:00Z", "group-stage",
            _comp_raw(_team_raw(23), "home", score="1"),
            _comp_raw(_team_raw(0), "away", score="1"),
            "post", "STATUS_FULL_TIME", period=2, completed=True,
            venue="Soldier Field")),
        espn.Match(_match_raw(
            "9203", "2026-06-20T21:00Z", "group-stage",
            _comp_raw(_team_raw(24), "home", score="2", winner=True),
            _comp_raw(_team_raw(0), "away", score="1"),
            "post", "STATUS_FULL_TIME", period=2, completed=True,
            venue="Arrowhead Stadium")),
        espn.Match(_match_raw(
            "9204", "2026-06-29T18:00Z", "round-of-32",
            _comp_raw(_team_raw(0), "home", score="3", winner=True),
            _comp_raw(_team_raw(25), "away", score="1"),
            "post", "STATUS_FULL_TIME", period=2, completed=True,
            venue="Rose Bowl")),
        espn.Match(_match_raw(
            "9205", "2026-07-04T18:00Z", "round-of-16",
            _comp_raw(_team_raw(0), "home"),
            _comp_raw(_team_raw(26), "away"),
            "pre", "STATUS_SCHEDULED", venue="NRG Stadium")),
        espn.Match(_match_raw(
            "9206", "2026-07-09T21:00Z", "quarterfinals",
            _comp_raw(_team_raw(0), "home"),
            _comp_raw(_team_raw(27), "away"),
            "pre", "STATUS_SCHEDULED", venue="Estadio Azteca")),
    ]
    for m in st.team_matches:
        st.match_index[m.id] = m
    return st


def state_help():
    return _base_state(S.HELP)
