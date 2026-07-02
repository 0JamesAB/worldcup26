"""
views.py - All screen rendering for the World Cup TUI.

render(state, cols, rows) -> list[str] (a full frame). Builds the chrome
(header / tabs / status / footer) and dispatches to the active view, which
draws onto a tui Canvas.
"""

import os
import re
import time
from datetime import datetime, timezone

_FAR = datetime.max.replace(tzinfo=timezone.utc)

from tui import term, widgets
from tui.canvas import Canvas, LIGHT, HEAVY
from tui.term import fg, bg, BOLD, DIM, ITALIC, RESET, fg_hex
import espn
import state as S
from palette import P


# ----------------------------------------------------------------------------
# small style helpers
# ----------------------------------------------------------------------------

def base():
    return bg(*P.bg0) + fg(*P.text)


def team_hex(tid=None, abbr=None):
    return espn.team_color(tid, abbr)


def real_team(abbr):
    """True if abbr is one of the 48 nations (not a bracket placeholder)."""
    rec = espn.fetch_team_colors().get(abbr)
    return bool(rec and rec.get("name"))


def status_text(m, frame):
    """(text, style) for a match's status chip."""
    if m.is_live:
        pulse = (frame // 3) % 2 == 0
        col = P.live if pulse else (60, 150, 95)
        clk = m.clock or m.detail or "LIVE"
        if m.status_name == "STATUS_HALFTIME":
            clk = "HT"
        return f"{clk}", fg(*col) + BOLD
    if m.is_post:
        if m.has_shootout:
            return "FT · pens", fg(*P.dim)
        if m.has_extra_time:
            return "AET", fg(*P.dim) + BOLD
        return "FT", fg(*P.dim) + BOLD
    # pre
    local = espn.to_local(m.date)
    if local:
        return local.strftime("%a %d %b · %H:%M"), fg(*P.accent2)
    return m.detail or "scheduled", fg(*P.accent2)


def score_str(c):
    if c is None or c.score is None:
        return "–"
    s = str(c.score)
    if c.shootout is not None:
        s += f" ({c.shootout})"
    return s


def team_goals_text(m, comp, maxw):
    """Compact scorer list for a competitor."""
    if not comp:
        return ""
    parts = []
    for g in m.goals:
        if g.team_id == comp.id:
            who = g.scorer.split()[-1] if g.scorer else "?"
            tag = ""
            if g.own_goal:
                tag = " (OG)"
            elif g.penalty:
                tag = " (P)"
            parts.append(f"{who} {g.minute}{tag}")
    txt = " · ".join(parts)
    return term.strip_ansi(term.truncate(txt, maxw)) if txt else ""


# ----------------------------------------------------------------------------
# odds (betting) — keyless, from ESPN's embedded sportsbook feed
# ----------------------------------------------------------------------------

def odds_enabled():
    """Odds show by default; WCUP_ODDS=off|0|false|no|hide hides them."""
    return (os.environ.get("WCUP_ODDS", "").strip().lower()
            not in ("0", "off", "false", "no", "hide"))


def _odds_format():
    v = os.environ.get("WCUP_ODDS_FORMAT", "").strip().lower()
    return v if v in ("american", "decimal") else "american"


def fmt_price(ml):
    """A single moneyline price in the user's preferred format."""
    if ml is None:
        return ""
    if _odds_format() == "decimal":
        d = espn.american_to_decimal(ml)
        return f"{d:.2f}" if d else ""
    return f"{ml:+d}"


def match_odds(m, detail=None):
    """The odds to display for a match, if any and if enabled."""
    if not odds_enabled():
        return None
    od = (m.odds if m else None) or (detail.odds if detail else None)
    if od and od.probabilities():
        return od
    return None


def _prob_rows(m, od):
    """[(name, abbr, hex_color_or_None, prob)] in Home / Draw / Away order."""
    ph, pd, pa = od.probabilities()
    home, away = (m.home if m else None), (m.away if m else None)
    return [
        (home.name if home else "Home", home.abbr if home else "1",
         team_hex(home.id, home.abbr) if home else None, ph),
        ("Draw", "X", None, pd),
        (away.name if away else "Away", away.abbr if away else "2",
         team_hex(away.id, away.abbr) if away else None, pa),
    ]


def _fit_label(name, abbr, w):
    """The full name if it fits `w` columns, else the abbreviation."""
    return name if term.display_width(name) <= w else abbr


def draw_odds_bars(rg, r, m, fillstyle, labelw=9):
    """Three implied-probability bars (home / draw / away) drawn into the
    card-inner Region `rg` starting at local row `r`. Returns rows used."""
    od = m.odds
    rows = _prob_rows(m, od)
    favi = max(range(3), key=lambda i: rows[i][3])
    bx = labelw + 2
    barmax = max(6, rg.w - labelw - 9)
    for i, (name, abbr, hexcol, p) in enumerate(rows):
        rr = r + i
        col = fg(*P.faint) if hexcol is None else fg_hex(hexcol)
        lbl_style = fillstyle + (fg(*P.white) + BOLD if i == favi else fg(*P.dim))
        rg.put(rr, 1, term.pad(_fit_label(name, abbr, labelw), labelw), lbl_style)
        rg.hbar(p, fillstyle + col, r=rr, c=bx, w=barmax,
                track_style=fillstyle + fg(*P.line))
        rg.put(rr, bx + barmax + 1, f"{round(p * 100):>2}%",
               fillstyle + (fg(*P.text) + BOLD if i == favi else fg(*P.dim)))
    return 3


def draw_odds_panel(rg, m, od):
    """A fuller odds panel for the match-centre body Region (pre-match)."""
    bw = min(66, rg.w - 6)
    cx = max(2, (rg.w - bw) // 2)
    rg.put(1, cx, "Match odds — implied win probability", fg(*P.gold) + BOLD)
    if od.provider:
        rg.put(1, cx + bw - term.display_width(od.provider), od.provider, fg(*P.faint))
    rows = _prob_rows(m, od)
    prices = [od.ml_home, od.ml_draw, od.ml_away]
    favi = max(range(3), key=lambda i: rows[i][3])
    labelw = 18
    bx = cx + labelw + 1
    barmax = max(8, bw - labelw - 12)
    r = 3
    for i, (name, abbr, hexcol, p) in enumerate(rows):
        col = fg(*P.faint) if hexcol is None else fg_hex(hexcol)
        rg.put(r, cx, term.pad(_fit_label(name, abbr, labelw), labelw),
               fg(*P.text) + (BOLD if i == favi else ""))
        rg.hbar(p, col, r=r, c=bx, w=barmax, track_style=fg(*P.line))
        rg.put(r, bx + barmax + 2, f"{round(p * 100):>2}%",
               fg(*P.text) + (BOLD if i == favi else ""))
        price = fmt_price(prices[i])
        if price:
            rg.put(r, bx + barmax + 7, price, fg(*P.dim))
        r += 1
    extras = []
    if od.over_under is not None:
        ou = f"O/U {od.over_under}"
        if od.over_odds is not None and od.under_odds is not None:
            ou += f"  (O {fmt_price(od.over_odds)} · U {fmt_price(od.under_odds)})"
        extras.append(ou)
    if od.spread_line:
        sp = f"Spread {od.spread_line}"
        if od.spread_odds is not None:
            sp += f" {fmt_price(od.spread_odds)}"
        extras.append(sp)
    if extras:
        rg.put(r + 1, cx, "     ".join(extras), fg(*P.dim))
    rg.put(r + 2, cx, "Lineups drop ~1h before kickoff.", fg(*P.faint) + ITALIC)


# ----------------------------------------------------------------------------
# chrome
# ----------------------------------------------------------------------------

def draw_header(bar, st, frame):
    bar.fill(bg(*P.bg1))
    # brand
    x = bar.gradient("⚽ FIFA WORLD CUP", (90, 210, 140), (120, 180, 255),
                     c=2, extra=bg(*P.bg1) + BOLD)
    bar.put(0, x + 1, "2026", bg(*P.bg1) + fg(*P.gold) + BOLD)
    # host
    bar.put(0, x + 6, "· USA · CAN · MEX", bg(*P.bg1) + fg(*P.faint))

    # live indicator + clock (right)
    live_n = sum(1 for m in st.matches_today if m.is_live)
    now = datetime.now().strftime("%H:%M:%S")
    right = f" {now} "
    if live_n:
        pulse = (frame // 3) % 2 == 0
        dot = "●" if pulse else "◍"
        chip = f"{dot} {live_n} LIVE "
        rx = bar.w - term.display_width(right) - term.display_width(chip) - 1
        bar.put(0, rx, chip, bg(*P.red if pulse else (150, 60, 60)) + fg(*P.white) + BOLD)
    else:
        chip = "○ no live "
        rx = bar.w - term.display_width(right) - term.display_width(chip) - 1
        bar.put(0, rx, chip, bg(*P.bg1) + fg(*P.faint))
    bar.right(right, bg(*P.bg1) + fg(*P.dim), pad=1)


def draw_tabs(bar, st):
    active = S.TAB_VIEWS.index(st.view) if st.view in S.TAB_VIEWS else -1
    extents = bar.tab_bar(S.TABS, active, hint="  :help  ·  q quit")
    for i, (x, w) in enumerate(extents):
        bar.hit(("view", S.TAB_VIEWS[i]), 0, x, 1, w)


def draw_context(bar, st, label):
    bar.fill(bg(*P.bg0))
    bar.put(0, 2, label, fg(*P.dim) + ITALIC)


def draw_statusline(bar, st):
    bar.fill(bg(*P.bg1))
    if st.command_mode:
        prompt = ":" + st.command_buf
        bar.put(0, 1, prompt, bg(*P.bg1) + fg(*P.white) + BOLD)
        x = 1 + term.display_width(prompt)
        bar.put(0, x, "█", bg(*P.bg1) + fg(*P.accent))
        # inline ghost completion of the highlighted suggestion
        _, sugg = S.command_completions(st, st.command_buf)
        if sugg:
            t = sugg[min(st.command_sel, len(sugg) - 1)]["text"]
            if t.startswith(st.command_buf) and len(t) > len(st.command_buf):
                ghost = t[len(st.command_buf):]
                bar.put(0, x + 1, term.strip_ansi(ghost), bg(*P.bg1) + fg(*P.faint))
                bar.put(0, x + 1 + term.display_width(ghost), "  ⇥ tab", bg(*P.bg1) + fg(*P.faint))
        return
    # latest live toast
    alive = [t for t in st.toasts if t.alive]
    if alive:
        t = alive[-1]
        if t.kind == "goal":
            stl = bg(*P.bg1) + fg(*P.gold) + BOLD
        elif t.kind == "error":
            stl = bg(*P.bg1) + fg(*P.red)
        else:
            stl = bg(*P.bg1) + fg(*P.accent)
        flash = (t.age < 1.2 and int(t.age * 5) % 2 == 0)
        if flash:
            stl = bg(*P.gold) + fg(*P.bg0) + BOLD
        bar.put(0, 1, " " + t.text + " ", stl)
    else:
        bar.put(0, 1, st.status, bg(*P.bg1) + fg(*P.faint))
    # net status right
    err = espn.last_error[0]
    if err:
        bar.right("⚠ reconnecting", bg(*P.bg1) + fg(*P.yellow), pad=1)


def draw_command_palette(root, st):
    """Floating command/argument suggestion menu above the ':' prompt."""
    title, sugg = S.command_completions(st, st.command_buf)
    if not sugg:
        return
    st.command_sel = max(0, min(st.command_sel, len(sugg) - 1))
    status_row = root.h - 2
    top_limit = 3  # don't cover header / tabs / context strip
    maxshow = max(1, min(len(sugg), status_row - top_limit - 1, 10))
    # keep the highlighted row within the visible window
    win_start = 0
    if st.command_sel >= maxshow:
        win_start = st.command_sel - maxshow + 1
    shown = sugg[win_start:win_start + maxshow]

    def rw(s):
        return term.display_width(s["label"]) + term.display_width(s["hint"]) + 8
    w = min(root.w - 4, max(48, term.display_width(title) + 8, max(rw(s) for s in shown)))
    h = len(shown) + 2
    y0 = status_row - h
    x0 = 1
    root.box(y0, x0, h, w, style=fg(*P.accent2), chars=LIGHT, title=title,
             title_style=fg(*P.gold) + BOLD, fillstyle=bg(*P.bg2))
    if len(sugg) > len(shown):
        more = f"{st.command_sel + 1}/{len(sugg)}"
        root.put(y0, x0 + w - term.display_width(more) - 2, more, bg(*P.bg2) + fg(*P.faint))
    for i, s in enumerate(shown):
        rr = y0 + 1 + i
        sel = (win_start + i) == st.command_sel
        if sel:
            root.fill_rect(rr, x0 + 1, 1, w - 2, bg(*P.accent2))
            root.put(rr, x0 + 1, " ▸ ", bg(*P.accent2) + fg(*P.bg0) + BOLD)
            lblst = bg(*P.accent2) + fg(*P.bg0) + BOLD
            hintst = bg(*P.accent2) + fg(*P.bg0)
        else:
            lblst = bg(*P.bg2) + fg(*P.text)
            hintst = bg(*P.bg2) + fg(*P.dim)
        root.put(rr, x0 + 4, term.strip_ansi(term.truncate(s["label"], w - 10)), lblst)
        hint = s.get("hint", "")
        if hint:
            hx = x0 + w - term.display_width(hint) - 2
            if hx > x0 + 4 + term.display_width(s["label"]) + 1:
                root.put(rr, hx, term.strip_ansi(hint), hintst)


def footer_right(st):
    """A useful, dynamic right-hand status: a live score, else next kickoff."""
    live = [m for m in st.matches_today if m.is_live]
    if live:
        m = live[0]
        return f"● {m.away.abbr} {m.away.score}-{m.home.score} {m.home.abbr} {m.clock}"
    now = datetime.now().astimezone()
    up = sorted((m for m in st.matches_today if m.is_pre and m.date),
                key=lambda m: m.date)
    if up:
        m = up[0]
        secs = (m.date - now).total_seconds()
        if secs > 0:
            hrs, mins = int(secs // 3600), int((secs % 3600) // 60)
            cd = f"{hrs}h{mins:02d}m" if hrs else f"{mins}m"
            return f"next: {m.away.abbr} v {m.home.abbr} · kickoff in {cd}"
    return ""


def draw_footer(bar, st):
    if st.command_mode:
        hints = [("⇥", "complete"), ("↑↓", "select"), ("↵", "run"), ("esc", "cancel")]
        widgets.footer(bar, 0, 0, bar.w, hints, right="")
        return
    common = [("↑↓", "move"), ("↵", "open"), ("⇥", "view"), (":", "command"), ("r", "refresh")]
    if st.view == S.SCHEDULE:
        hints = [("←→", "day")] + common[:4] + [("r", "refresh")]
    elif st.view == S.BRACKET:
        hints = [("←→↑↓", "scroll"), ("⇥", "view"), (":", "command"), ("q", "quit")]
    elif st.view == S.SCORERS:
        hints = [("←→", "goals/assists"), ("⇥", "view"), (":", "command"), ("q", "quit")]
    elif st.view == S.DETAIL:
        hints = [("←→", "tabs"), ("↑↓", "scroll"), ("esc", "back"), (":", "command")]
    elif st.view in (S.HELP, S.TEAM):
        hints = [("esc", "back"), ("⇥", "view"), (":", "command"), ("q", "quit")]
    else:
        hints = common
    widgets.footer(bar, 0, 0, bar.w, hints, right=footer_right(st))


# ----------------------------------------------------------------------------
# match widgets
# ----------------------------------------------------------------------------

def card_rows(m):
    """Total rows a card consumes (box height + 1 gap): 5, or 8 with odds bars."""
    return 8 if (m.is_pre and match_odds(m)) else 5


def draw_match_card(card, m, selected, frame):
    """A match card filling the Region `card` (4 rows tall, or 7 when
    pre-match odds bars are shown — size it with card_rows)."""
    show_odds = m.is_pre and match_odds(m)
    if m.is_live:
        border = fg(*P.live)
    elif m.is_post:
        border = fg(*P.line)
    else:
        border = fg(*P.accent2)
    if selected:
        border = fg(*P.gold) + BOLD
    fillstyle = bg(*(P.bg2 if selected else P.bg1))
    # title: round · venue (left), status (right)
    rnd = espn.ROUND_LABEL.get(m.season_slug, m.season_slug.replace("-", " ").title())
    venue = m.venue or ""
    title = f" {rnd}"
    if venue:
        title += f" · {venue}"
    title += " "
    stxt, sstyle = status_text(m, frame)
    inner = card.card(border_style=border, fill_style=fillstyle, chars=LIGHT,
                      title=title, title_style=fillstyle + fg(*P.dim),
                      right=stxt, right_style=fillstyle + sstyle,
                      selected=selected, select_style=fg(*P.gold) + BOLD)

    # two team rows: away then home
    for i, comp in enumerate((m.away, m.home)):
        if not comp:
            continue
        inner.put(i, 0, "●", fillstyle + fg_hex(team_hex(comp.id, comp.abbr)))
        is_win = comp.winner and m.is_post
        nstyle = fillstyle + (fg(*P.white) + BOLD if is_win else fg(*P.text))
        inner.put(i, 2, comp.name, nstyle, max_w=18)
        # score
        sc = score_str(comp)
        sstyle2 = fillstyle + (fg(*P.gold) + BOLD if (is_win or m.is_live) else fg(*P.text) + BOLD)
        if m.is_pre:
            sc = ""
        inner.put(i, 22, term.pad(sc, 7, "right"), sstyle2)
        # scorers
        gtxt = team_goals_text(m, comp, inner.w - 31)
        if gtxt:
            inner.put(i, 31, gtxt, fillstyle + fg(*P.faint))
        elif m.is_pre and comp.form:
            inner.put(i, 31, "form " + comp.form, fillstyle + fg(*P.faint))

    if show_odds:
        draw_odds_bars(inner, 2, m, fillstyle)
        prov = f" {m.odds.provider or 'odds'} "
        card.put(card.h - 1, max(2, (card.w - term.display_width(prov)) // 2),
                 prov, fg(*P.faint))


def compact_status(m, frame):
    if m.is_live:
        pulse = (frame // 3) % 2 == 0
        return (m.clock or "LIVE"), fg(*(P.live if pulse else (60, 150, 95))) + BOLD
    if m.is_post:
        label = "FT · pens" if m.has_shootout else ("AET" if m.has_extra_time else "FT")
        return label, fg(*P.dim) + BOLD
    return "—", fg(*P.faint)


def draw_compact_row(row, m, selected, frame, left="time"):
    """One fixture line in a full-width single-row Region (2-col gutters)."""
    fillstyle = bg(*(P.bg2 if selected else P.bg0))
    row.fill_rect(0, 2, 1, row.w - 4, fillstyle)
    if selected:
        row.put(0, 2, "▸", fg(*P.gold) + BOLD)
    local = espn.to_local(m.date)
    if left == "date":
        tstr = local.strftime("%b %d") if local else "--"
    else:
        tstr = local.strftime("%H:%M") if local else "--:--"
    row.put(0, 4, term.pad(tstr, 6), fillstyle + fg(*P.faint))
    a, hh = m.away, m.home
    aw = bool(a and a.winner and m.is_post)
    hw = bool(hh and hh.winner and m.is_post)
    x = 11
    if a:
        row.put(0, x, "●", fillstyle + fg_hex(team_hex(a.id, a.abbr)))
        row.put(0, x + 2, term.pad(term.strip_ansi(term.truncate(a.name, 18)), 18),
                fillstyle + (fg(*P.white) + BOLD if aw else fg(*P.text)))
    sa = score_str(a) if not m.is_pre else ""
    sh = score_str(hh) if not m.is_pre else ""
    mid = f"{sa} - {sh}" if not m.is_pre else "v"
    row.put(0, x + 21, term.pad(mid, 9, "center"),
            fillstyle + (fg(*P.gold) + BOLD if m.is_live else fg(*P.text) + BOLD))
    if hh:
        row.put(0, x + 31, "●", fillstyle + fg_hex(team_hex(hh.id, hh.abbr)))
        row.put(0, x + 33, term.pad(term.strip_ansi(term.truncate(hh.name, 18)), 18),
                fillstyle + (fg(*P.white) + BOLD if hw else fg(*P.text)))
    cs, cstyle = compact_status(m, frame)
    row.put(0, x + 52, term.pad(term.strip_ansi(cs), 10), fillstyle + cstyle)
    vx = x + 63
    if m.venue and vx < row.w - 6:
        row.put(0, vx, term.strip_ansi(term.truncate(m.venue, row.w - vx - 3)),
                fillstyle + fg(*P.faint))


# ----------------------------------------------------------------------------
# views
# ----------------------------------------------------------------------------

def view_live(rg, st, frame):
    """Today's match cards. `rg` includes the context row (local row 0) so
    the overflow counter can sit there; cards fill the body below it."""
    body = rg.rows(1)
    matches = list(st.matches_today)
    if not matches:
        center_msg(body, 0, body.h - 1, body.w, "No matches today.  Try  :schedule  to browse fixtures.")
        return
    # order: live first, then pre, then post
    order = {"in": 0, "pre": 1, "post": 2}
    matches.sort(key=lambda m: (order.get(m.state, 3), m.date or _FAR))
    st.live_sel = max(0, min(st.live_sel, len(matches) - 1))

    card_w = min(78, rg.w - 4)
    col_x = max(2, (rg.w - card_w) // 2)
    # Cards vary in height (pre-match cards carry odds bars), so scroll by
    # advancing the start index until the selected card fits on screen.
    avail = body.h
    start = 0
    # advance `start` until the run start..sel fits; keep the running sum O(n)
    used = sum(card_rows(matches[k]) for k in range(st.live_sel + 1))
    while start < st.live_sel and used > avail:
        used -= card_rows(matches[start])
        start += 1
    r = 0
    shown = 0
    for i in range(start, len(matches)):
        cons = card_rows(matches[i])
        # box occupies cons-1 rows; keep whole cards (but always draw the first)
        if shown > 0 and r + cons - 2 > body.h - 1:
            break
        card = body.sub(r, col_x, cons - 1, card_w)
        draw_match_card(card, matches[i], i == st.live_sel, frame)
        card.hit(("sel", "live_sel", i, True))
        r += cons
        shown += 1
    if shown < len(matches):
        # counter on the context row, clear of the cards
        rg.right(f"▲▼ {st.live_sel + 1}/{len(matches)}", fg(*P.faint), pad=2)


def view_schedule(rg, st, frame):
    # date nav header
    d = st.schedule_date
    try:
        dt = datetime.strptime(d, "%Y%m%d")
        dstr = dt.strftime("%A · %d %B %Y")
    except ValueError:
        dstr = d
    nav = f"◂  {dstr}  ▸"
    nx = max(2, (rg.w - term.display_width(nav)) // 2)
    rg.put(0, nx, nav, fg(*P.text) + BOLD)
    nw = term.display_width(nav)
    rg.hit(("sched_day", -1), 0, nx - 1, 1, 3)
    rg.hit(("sched_day", 1), 0, nx + nw - 2, 1, 3)
    if st.schedule_label:
        rg.put(0, 2, st.schedule_label, fg(*P.gold))
    if "schedule" in st.loading:
        rg.put(0, rg.w - 12, "loading…", fg(*P.faint) + ITALIC)
    rg.hline(1, 2, rg.w - 4, fg(*P.line))

    matches = list(st.schedule_matches)
    if not matches:
        center_msg(rg, 2, rg.h - 1, rg.w, "No fixtures on this date.   ←/→ to change day")
        return
    st.sched_sel = max(0, min(st.sched_sel, len(matches) - 1))
    r = 2
    # simple scroll window
    avail = rg.h - r
    start = max(0, st.sched_sel - avail + 2) if st.sched_sel >= avail else 0
    for i in range(start, len(matches)):
        if r >= rg.h:
            break
        row = rg.rows(r, r + 1)
        draw_compact_row(row, matches[i], i == st.sched_sel, frame)
        row.hit(("sel", "sched_sel", i, True), 0, 2, 1, row.w - 4)
        r += 1


def view_groups(rg, st, frame):
    groups = st.standings
    if not groups:
        center_msg(rg, 0, rg.h - 1, rg.w, "Loading group tables…")
        return
    gw = 42
    ncols = max(1, min(4, (rg.w - 2) // gw))
    gw = min(48, (rg.w - 2) // ncols)
    gh = 7  # title + sep + header + 4 rows
    rows_per_screen = rg.h // gh
    total_rows = (len(groups) + ncols - 1) // ncols
    st.groups_scroll = max(0, min(st.groups_scroll, max(0, total_rows - rows_per_screen)))
    skip = st.groups_scroll * ncols
    r = 0
    idx = skip
    while idx < len(groups) and r + gh - 1 <= rg.h:
        for cc in range(ncols):
            if idx >= len(groups):
                break
            draw_group_table(rg.sub(r, 2 + cc * gw, gh, gw - 2), groups[idx])
            idx += 1
        r += gh
    if total_rows > rows_per_screen:
        rg.put(rg.h - 1, rg.w - 22, f"↑↓ scroll  {st.groups_scroll+1}/{max(1,total_rows-rows_per_screen+1)}",
               fg(*P.faint))


def draw_group_table(rg, g):
    # column layout: rank / header-# / swatch / flex team / Pl / GD / Pts
    cols_spec = [("", 1, "left"), ("#", 1, "left"), ("", 2, "left"),
                 ("Team", -1, "left"), ("Pl", 4, "left"),
                 ("GD", 5, "left"), ("Pts", 4, "left")]
    rows = []
    for i, row in enumerate(g.rows[:4]):
        rank = row.rank or (i + 1)
        if row.qual_color:
            qrgb = term.hex_rgb(row.qual_color) or P.dim
        elif rank <= 2:
            qrgb = P.accent
        elif rank == 3:
            qrgb = P.gold
        else:
            qrgb = P.faint
        if rank <= 2:
            namecol = fg(*P.white) + BOLD
        elif rank >= 4:
            namecol = fg(*P.dim)
        else:
            namecol = fg(*P.text)
        label = f"{row.abbr} {row.name}"
        rows.append([
            (str(rank), fg(*qrgb) + BOLD),
            None,
            ("▌", fg_hex(team_hex(row.id, row.abbr))),
            (term.strip_ansi(term.truncate(label, rg.w - 18)), namecol),
            (f"{row.gp:>2}", fg(*P.dim)),
            (term.pad(str(row.gd_disp), 3, "right"), fg(*P.text)),
            (term.pad(str(row.pts), 3, "right"), fg(*P.gold) + BOLD),
        ])
    rg.table(cols_spec, rows,
             title=g.name, title_style=fg(*P.gold) + BOLD,
             rule_style=fg(*P.line), header_style=fg(*P.faint))


def view_bracket(cv, top, bottom, cols, st, frame):
    br = st.bracket
    if not br or not any(br.values()):
        center_msg(cv, top, bottom, cols, "Loading knockout bracket…")
        return
    big, cells = build_bracket_canvas(br, frame)
    vh = bottom - top + 1
    vw = cols - 2
    st.bracket_scroll_y = max(0, min(st.bracket_scroll_y, max(0, big.h - vh)))
    st.bracket_scroll_x = max(0, min(st.bracket_scroll_x, max(0, big.w - vw)))
    oy, ox = st.bracket_scroll_y, st.bracket_scroll_x
    # register the visible slice of each match box as clickable
    for cy, cx, m in cells:
        if not m:
            continue
        r0 = top + (cy - 1) - oy          # box top row on screen
        c0 = 2 + cx - ox
        rr = max(r0, top)
        rc = max(c0, 2)
        rh = min(r0 + 4, bottom + 1) - rr
        rw = min(c0 + CELL_W, 2 + vw) - rc
        st.hits.add(rr, rc, rh, rw, ("open", m.id))
    for y in range(vh):
        sy = y + oy
        if sy >= big.h:
            break
        for x in range(vw):
            sx = x + ox
            if sx >= big.w:
                break
            src = big.grid[sy][sx]
            dst = cv.grid[top + y][2 + x]
            dst.ch, dst.style, dst.cont = src.ch, src.style, src.cont
    # scroll position indicator on the context strip area (row 2 handled elsewhere)
    if big.h > vh:
        pct = int(100 * oy / max(1, big.h - vh))
        cv.put(top, cols - 9, f"{pct:>3}% ▼", bg(*P.bg0) + fg(*P.faint))


CELL_W = 20
COL_GAP = 7
UNIT = 4  # rows allocated per Round-of-32 match


KO_ORDER = ["round-of-32", "round-of-16", "quarterfinals", "semifinals", "final"]
KO_PREV = {b: a for a, b in zip(KO_ORDER, KO_ORDER[1:])}
_ROUND_LABELS = {slug: label for slug, label, _ in espn.KNOCKOUT_ROUNDS}
# Placeholder names on undecided fixtures, e.g. "Round of 16 5 Winner".
_PLACEHOLDER_RE = re.compile(
    r"(Round of 32|Round of 16|Quarterfinal|Semifinal)\s+(\d+)\s+Winner", re.I)


def _match_winner(m):
    if not m:
        return None
    if m.home and m.home.winner:
        return m.home
    if m.away and m.away.winner:
        return m.away
    return None


def _feeder_index(comp, prev_matches):
    """Index of the previous-round match that feeds this slot, or None.

    Undecided slots carry a placeholder ("Round of 16 5 Winner"); decided
    slots carry the real team, so we match it back to the match it won.
    """
    if comp is None:
        return None
    mo = _PLACEHOLDER_RE.search(comp.name or "")
    if mo:
        return int(mo.group(2)) - 1
    for i, pm in enumerate(prev_matches):
        w = _match_winner(pm)
        if not w:
            continue
        if comp.id and w.id and comp.id == w.id:
            return i
        if comp.abbr and comp.abbr == w.abbr and real_team(comp.abbr):
            return i
    return None


def _bracket_model(br):
    """(numbered, feeders): matches per round ordered by canonical match number
    and feeders[(slug,i)] = (away_idx, home_idx).

    The match number (used by "Round of 32 N Winner" placeholders) follows the
    kickoff schedule, not ESPN's internal event id — so index i here is match
    N=i+1. Sort by (date, id) so the id only breaks exact-time ties stably.
    """
    numbered = {
        slug: sorted(br.get(slug, []),
                     key=lambda m: (m.date or _FAR,
                                    int(m.id) if str(m.id).isdigit() else 1 << 30))
        for slug in KO_ORDER
    }
    feeders = {}
    for slug in KO_ORDER[1:]:
        prev = numbered[KO_PREV[slug]]
        for i, m in enumerate(numbered[slug]):
            feeders[(slug, i)] = (_feeder_index(m.away, prev),
                                  _feeder_index(m.home, prev))
    return numbered, feeders


def build_bracket_canvas(br, frame):
    """Returns (canvas, cells) where cells is [(cy, cx, match)] for hit-testing."""
    numbered, feeders = _bracket_model(br)
    sizes = [len(numbered.get(slug, [])) for slug in KO_ORDER]
    ridx = {slug: i for i, slug in enumerate(KO_ORDER)}
    idx_feeders = {(ridx[slug], i): v for (slug, i), v in feeders.items()}
    cells = []

    def cell(cv, cy, cx, ri, i):
        m = numbered[KO_ORDER[ri]][i]
        cells.append((cy, cx, m))
        draw_bracket_cell(cv, cy, cx, m, frame)

    cv, colx, ypos = widgets.draw_bracket(
        sizes, idx_feeders, cell,
        labels=[_ROUND_LABELS.get(s, s) for s in KO_ORDER],
        label_style=fg(*P.gold) + BOLD, connector_style=fg(*P.line),
        bg_style=bg(*P.bg0), unit=UNIT, cell_w=CELL_W, col_gap=COL_GAP,
        fallback_leaves=16)

    # 3rd-place match under the final column
    third = br.get("3rd-place-match", [])
    if third:
        fin = len(KO_ORDER) - 1
        ty = int(round(ypos.get((fin, 0), 2))) + 5
        if ty + 3 < cv.h:
            cv.put(ty - 2, colx[fin] + 3, "3rd Place", fg(*P.dim) + BOLD)
            draw_bracket_cell(cv, ty, colx[fin], third[0], frame)
            cells.append((ty, colx[fin], third[0]))
    return cv, cells


def draw_bracket_cell(cv, cy, cx, m, frame):
    """4-row box centred so the two team rows sit at cy and cy+1."""
    w = CELL_W
    top = cy - 1
    border = fg(*P.line)
    if m and m.is_live:
        border = fg(*P.live)
    elif m and m.is_post and m.season_slug == "final":
        border = fg(*P.gold)
    cv.box(top, cx, 4, w, style=border, chars=LIGHT, fillstyle=bg(*P.bg1))
    inner = bg(*P.bg1)
    if not m:
        cv.put(cy, cx + 2, term.pad("—", w - 4), inner + fg(*P.faint))
        cv.put(cy + 1, cx + 2, term.pad("—", w - 4), inner + fg(*P.faint))
        return
    for i, comp in enumerate((m.away, m.home)):
        rr = cy + i
        if rr >= cv.h or comp is None:
            continue
        placeholder = not real_team(comp.abbr)
        abbr = comp.abbr if not placeholder else "TBD"
        win = comp.winner and m.is_post
        nm_style = inner + (fg(*P.white) + BOLD if win else
                            (fg(*P.faint) if placeholder else fg(*P.text)))
        cv.put(rr, cx + 1, "▌", inner + fg_hex(team_hex(comp.id, comp.abbr)))
        cv.put(rr, cx + 2, term.pad(abbr, 5), nm_style)
        if not m.is_pre:
            sc = comp.score if comp.score is not None else "0"
            if comp.shootout is not None:
                cv.put(rr, cx + w - 7, f"{sc} ({comp.shootout})",
                       inner + (fg(*P.gold) + BOLD if win else fg(*P.text)))
            else:
                cv.put(rr, cx + w - 3, term.pad(str(sc), 2, "right"),
                       inner + (fg(*P.gold) + BOLD if win else fg(*P.text)))
        if win:
            cv.put(rr, cx + w - 1, "‹", inner + fg(*P.gold))


def view_scorers(rg, st, frame):
    tabs = [("Goals", "goals"), ("Assists", "assists")]
    x = 2
    for i, (lbl, _) in enumerate(tabs):
        on = i == st.scorers_tab
        stl = (bg(*P.gold) + fg(*P.bg0) + BOLD) if on else (bg(*P.bg1) + fg(*P.dim))
        icon = "⚽ " if i == 0 else "🅰 "
        rg.put(0, x, f" {icon}{lbl} ", stl)
        tw = term.display_width(f" {icon}{lbl} ")
        rg.hit(("scorers_tab", i), 0, x, 1, tw)
        x += tw + 1
    rg.put(0, rg.w - 18, "←→ switch board", fg(*P.faint))
    rg.hline(1, 2, rg.w - 4, fg(*P.line))

    key = "goals" if st.scorers_tab == 0 else "assists"
    rows = st.scorers.get(key, [])
    if not rows:
        center_msg(rg, 2, rg.h - 1, rg.w, "Loading leaderboard…")
        return
    maxval = max((r["value"] for r in rows), default=1) or 1
    barmax = min(40, rg.w - 46)
    r = 3
    st.scorers_sel = max(0, min(st.scorers_sel, len(rows) - 1))
    for i, row in enumerate(rows):
        if r >= rg.h:
            break
        sel = i == st.scorers_sel
        line = rg.rows(r, r + 1)
        if sel:
            line.fill_rect(0, 2, 1, line.w - 4, bg(*P.bg2))
        bgs = bg(*P.bg2) if sel else bg(*P.bg0)
        medal = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, f"{i+1:>2}")
        line.put(0, 3, str(medal), bgs + fg(*P.gold))
        line.put(0, 7, "●", bgs + fg_hex(team_hex(row.get("team_id"), row.get("team_abbr"))))
        line.put(0, 9, term.pad(row["name"], 24), bgs + fg(*P.text) + (BOLD if i < 3 else ""))
        line.put(0, 34, term.pad(row.get("team_abbr", ""), 5), bgs + fg(*P.dim))
        # bar — value sits right after the bar's fill so it tracks the bar length
        bx = 40
        filln = line.hbar(row["value"] / maxval,
                          bgs + fg_hex(team_hex(row.get("team_id"), row.get("team_abbr"))),
                          c=bx, w=barmax)
        line.put(0, bx + filln + 1, str(row["value"]), bgs + fg(*P.gold) + BOLD)
        line.hit(("sel", "scorers_sel", i, False), 0, 2, 1, line.w - 4)
        r += 1


# ----------------------------------------------------------------------------
# match detail
# ----------------------------------------------------------------------------

DETAIL_TABS = ["Lineups", "Timeline", "Stats"]


def view_detail(rg, st, frame):
    """Match centre. `rg` spans the body rows below the context strip."""
    eid = st.detail_event_id
    detail = st.summaries.get(eid)
    m = st.match_index.get(eid)
    if m is None and detail is not None:
        m = detail.header_match
    if m is not None and not m.venue and detail is not None and detail.venue:
        m.venue = detail.venue
    # score header (with a compact odds strip for upcoming matches)
    od = match_odds(m, detail)
    draw_detail_header(rg.rows(0, 3), m, frame, od)
    # tabs
    x = 2
    for i, lbl in enumerate(DETAIL_TABS):
        on = i == st.detail_tab
        stl = (bg(*P.accent) + fg(*P.bg0) + BOLD) if on else (bg(*P.bg1) + fg(*P.dim))
        rg.put(4, x, f" {lbl} ", stl)
        rg.hit(("detail_tab", i), 4, x, 1, term.display_width(lbl) + 2)
        x += term.display_width(lbl) + 3
    rg.put(4, rg.w - 16, "←→ tabs · esc back", fg(*P.faint))
    rg.hline(5, 2, rg.w - 4, fg(*P.line))
    body = rg.rows(6)
    if detail is None:
        center_msg(body, 0, body.h - 1, body.w, "Loading match details…")
        return
    if st.detail_tab == 0:
        draw_lineups(body, m, detail)
    elif st.detail_tab == 1:
        draw_timeline(body, m, detail, st)
    else:
        draw_stats(body, m, detail)


def draw_detail_odds_strip(rg, m, od):
    """One-line moneyline strip (shown on every detail tab for pre-match).
    `rg` is the single strip row."""
    x = rg.put(0, 2, "Odds", bg(*P.bg1) + fg(*P.faint)) + 2
    for i, (name, abbr, hexcol, p) in enumerate(_prob_rows(m, od)):
        if i:
            x = rg.put(0, x, "·", bg(*P.bg1) + fg(*P.faint)) + 1
        col = fg(*P.faint) if hexcol is None else fg_hex(hexcol)
        x = rg.put(0, x, abbr, bg(*P.bg1) + col + BOLD) + 1
        x = rg.put(0, x, f"{round(p * 100)}%", bg(*P.bg1) + fg(*P.text)) + 1
    right = ""
    if od.over_under is not None:
        right += f"O/U {od.over_under}    "
    right += od.provider or ""
    if right.strip():
        rx = rg.w - term.display_width(right) - 2
        if rx > x + 2:
            rg.put(0, rx, right, bg(*P.bg1) + fg(*P.faint))


def draw_detail_header(rg, m, frame, od=None):
    """Three-row score header filling the Region `rg`."""
    rg.fill(bg(*P.bg1))
    if not m:
        rg.put(1, 2, "match", fg(*P.text) + BOLD)
        return
    a, h = m.away, m.home
    rnd = espn.ROUND_LABEL.get(m.season_slug, "")
    rg.put(0, 2, f"{rnd}  ·  {m.venue}", bg(*P.bg1) + fg(*P.dim))
    stxt, sstyle = status_text(m, frame)
    rg.right(stxt, bg(*P.bg1) + sstyle, pad=2)
    # big score line
    aw = (a.name if a else "?")
    hw = (h.name if h else "?")
    sc = f"{score_str(a)}  -  {score_str(h)}"
    line = f"{aw}    {sc}    {hw}"
    cx = max(2, (rg.w - term.display_width(line)) // 2)
    (rg.at(1, cx)
       .write("● ", bg(*P.bg1) + fg_hex(team_hex(a.id if a else None, a.abbr if a else None)))
       .write(aw, bg(*P.bg1) + fg(*P.white) + BOLD + (BOLD if a and a.winner else ""))
       .write("    ", bg(*P.bg1))
       .write(sc, bg(*P.bg1) + fg(*P.gold) + BOLD)
       .gap(4)
       .write(hw, bg(*P.bg1) + fg(*P.white) + BOLD)
       .gap(1)
       .write(" ●", bg(*P.bg1) + fg_hex(team_hex(h.id if h else None, h.abbr if h else None))))
    if od is not None and m.is_pre:
        draw_detail_odds_strip(rg.rows(2, 3), m, od)


def draw_lineups(rg, m, detail):
    if not detail.lineups:
        od = match_odds(m, detail)
        if od:
            draw_odds_panel(rg, m, od)
        else:
            center_msg(rg, 0, rg.h - 1, rg.w, "Lineups not available yet (released ~1h before kickoff).")
        return
    # away on left pitch-half, home on right; or stacked pitch. Use a vertical
    # pitch split into two halves stacked: away top, home bottom.
    away = next((l for l in detail.lineups if l.home_away == "away"), detail.lineups[0])
    home = next((l for l in detail.lineups if l.home_away == "home"),
                detail.lineups[-1])
    pitch_w = min(rg.w - 4, 96)
    px = 2 + (rg.w - 4 - pitch_w) // 2
    draw_pitch(rg.sub(0, px, rg.h, pitch_w), away, home, m)


def formation_lines(lineup):
    """Return list of rows (each a list of RosterPlayer) from GK to forwards."""
    starters = [p for p in lineup.starters]
    # order by formationPlace if available
    def fp(p):
        try:
            return int(p.formation_place)
        except (TypeError, ValueError):
            return 99
    starters.sort(key=fp)
    rows = []
    if lineup.formation and "-" in lineup.formation:
        try:
            chunks = [1] + [int(x) for x in lineup.formation.split("-")]
        except ValueError:
            chunks = None
    else:
        chunks = None
    if chunks and sum(chunks) == len(starters):
        idx = 0
        for ccount in chunks:
            rows.append(starters[idx:idx + ccount])
            idx += ccount
    else:
        # fallback: group by position bucket
        buckets = {"G": [], "D": [], "M": [], "F": []}
        for p in starters:
            pa = (p.pos or "M")[0].upper()
            if pa in ("G",):
                buckets["G"].append(p)
            elif pa in ("D", "B"):
                buckets["D"].append(p)
            elif pa in ("F", "S", "W"):
                buckets["F"].append(p)
            else:
                buckets["M"].append(p)
        rows = [buckets["G"], buckets["D"], buckets["M"], buckets["F"]]
        rows = [r for r in rows if r]
    return rows


def draw_pitch(rg, away, home, m):
    """The stacked lineup pitch filling the Region `rg` (away top half)."""
    pitch_style = bg(*P.pitch) + fg(*(210, 235, 215))
    rg.fill(pitch_style)
    # stripes
    stripe_style = bg(*(36, 120, 70)) + fg(*(210, 235, 215))
    for x in range(0, rg.w, 8):
        rg.fill_rect(0, x, rg.h, min(4, rg.w - x), stripe_style)
    midy = rg.h // 2
    rg.hline(midy, 0, rg.w, bg(*P.pitch) + fg(*(150, 200, 165)), "─")
    rg.put(midy, rg.w // 2 - 1, "◯", bg(*P.pitch) + fg(*(150, 200, 165)))

    # away occupies top half (rows 0..midy-1), home bottom half
    half = rg.h // 2
    aw_rows = formation_lines(away)
    hm_rows = formation_lines(home)
    # away: GK near top edge -> forwards near mid
    place_formation(rg, 0, half - 1, aw_rows, away, m, invert=False)
    place_formation(rg, midy + 1, half - 1, hm_rows, home, m, invert=True)
    # team labels
    rg.put(0, 1, f" {away.abbr} {away.formation} ▲ ", bg(*P.bg1) + fg_hex(team_hex(away.team_id, away.abbr)) + BOLD)
    rg.put(rg.h - 1, 1, f" {home.abbr} {home.formation} ▼ ", bg(*P.bg1) + fg_hex(team_hex(home.team_id, home.abbr)) + BOLD)


def place_formation(rg, y0, height, rows, lineup, m, invert):
    """Lay one team's lines onto the FULL pitch Region `rg`, offset by the
    local row `y0` (never a half sub-region: inverted front lines print
    names at ry-1, on the midline row)."""
    if not rows:
        return
    n = len(rows)
    for li, line in enumerate(rows):
        if not line:
            continue
        frac = (li + 0.5) / n
        if invert:
            frac = 1 - frac
        ry = y0 + int(frac * (height - 1))
        k = len(line)
        for pi, p in enumerate(line):
            cx = int((pi + 0.5) / k * rg.w)
            chip = f"{p.jersey}"
            col = fg_hex(team_hex(lineup.team_id, lineup.abbr))
            rg.put(ry, cx - 1, "▟", bg(*P.pitch) + col)
            rg.put(ry, cx, chip, bg_team(lineup) + fg(*P.bg0) + BOLD)
            # name below
            nm = p.short or p.name
            nm = nm.split()[-1] if nm else "?"
            nx = cx - len(nm) // 2
            rg.put(ry + (1 if not invert else -1), max(0, nx), term.strip_ansi(term.truncate(nm, 12)),
                   bg(*P.pitch) + fg(*(235, 245, 235)) + BOLD)


def bg_team(lineup):
    rgb = term.hex_rgb(team_hex(lineup.team_id, lineup.abbr)) or (200, 200, 200)
    return bg(*rgb)


def draw_timeline(rg, m, detail, st):
    events = [e for e in detail.key_events
              if e.type in ("Goal", "Yellow Card", "Red Card", "Substitution",
                            "Penalty - Scored", "Penalty - Missed") or e.scoring]
    if not events:
        center_msg(rg, 0, rg.h - 1, rg.w, "No key events yet.")
        return
    away_id = m.away.id if m and m.away else None
    spine = rg.w // 2
    rg.vline(0, spine, style=fg(*P.line), ch="┊")
    # team headers
    if m and m.away:
        rg.put(0, spine - 6 - term.display_width(m.away.name), m.away.name,
               fg_hex(team_hex(m.away.id, m.away.abbr)) + BOLD)
    st.detail_scroll = max(0, min(st.detail_scroll, max(0, len(events) - (rg.h - 1))))
    r = 1
    for e in events[st.detail_scroll:]:
        if r >= rg.h:
            break
        icon, istyle = event_icon(e)
        is_away = e.team_id == away_id
        if e.type == "Substitution" and len(e.players) >= 2:
            label = f"{e.players[0]} ↑ {e.players[1]} ↓"
        else:
            label = (e.players[0] if e.players else e.team)
        minute = e.minute or ""
        # minute chip sits on the spine (no icon overlap)
        rg.put(r, spine - 3, term.pad(minute, 7, "center"), bg(*P.bg2) + fg(*P.gold) + BOLD)
        label = term.strip_ansi(label)
        if is_away:
            text = f"{label} {icon}"
            tx = spine - 4 - term.display_width(term.strip_ansi(text))
            rg.put(r, max(2, tx), term.strip_ansi(text),
                   (fg(*P.white) + BOLD if e.scoring else istyle))
        else:
            text = f"{icon} {label}"
            rg.put(r, spine + 4, term.strip_ansi(text),
                   (fg(*P.white) + BOLD if e.scoring else istyle))
        r += 1


def event_icon(e):
    t = e.type
    if e.scoring or t.startswith("Goal") or "Penalty - Scored" in t:
        return "⚽", fg(*P.white) + BOLD
    if t == "Yellow Card":
        return "🟨", fg(*P.yellow)
    if t == "Red Card":
        return "🟥", fg(*P.red) + BOLD
    if t == "Substitution":
        return "🔁", fg(*P.dim)
    return "•", fg(*P.dim)


def draw_stats(rg, m, detail):
    rows = detail.team_stats()
    if not rows:
        center_msg(rg, 0, rg.h - 1, rg.w, "Match stats not available yet.")
        return
    a = m.away.abbr if m and m.away else "AWAY"
    h = m.home.abbr if m and m.home else "HOME"
    acol = fg_hex(team_hex(m.away.id if m and m.away else None, a))
    hcol = fg_hex(team_hex(m.home.id if m and m.home else None, h))
    rg.put(0, 6, a, acol + BOLD)
    rg.put(0, rg.w - 6 - term.display_width(h), h, hcol + BOLD)
    rg.put(0, (rg.w - 8) // 2, "stat", fg(*P.faint))
    r = 2
    for label, av, hv in rows:
        if r >= rg.h:
            break
        # split bar centered: away grows left from mid, home grows right
        r += rg.duel(label, av, hv, acol, hcol, r=r, c=6, w=rg.w - 12,
                     label_style=fg(*P.dim),
                     track_style=bg(*P.bg1),
                     lval_style=acol + BOLD,
                     rval_style=hcol + BOLD,
                     divider_style=fg(*P.faint))


# ----------------------------------------------------------------------------
# team view
# ----------------------------------------------------------------------------

def view_team(rg, st, frame):
    name = getattr(st, "team_query", "")
    abbr = getattr(st, "team_abbr", "")
    rec = espn.fetch_team_colors().get(abbr, {})
    col = team_hex(abbr=abbr)
    rg.fill_rect(0, 0, 2, rg.w, bg(*P.bg1))
    rg.put(0, 2, "███ ", bg(*P.bg1) + fg_hex(col))
    rg.put(0, 6, name, bg(*P.bg1) + fg(*P.white) + BOLD)
    rg.put(0, 6 + term.display_width(name) + 2, abbr, bg(*P.bg1) + fg_hex(col) + BOLD)
    matches = getattr(st, "team_matches", [])
    # record summary (played matches only)
    w = d = l = gf = ga = 0
    nxt = None
    for m in matches:
        side = m.home if (m.home and m.home.abbr == abbr) else m.away
        opp = m.away if side is m.home else m.home
        if m.is_post and side and opp:
            sf, sa = side.score_int, opp.score_int
            if sf is not None and sa is not None:
                gf += sf; ga += sa
                if side.winner:
                    w += 1
                elif opp.winner:
                    l += 1
                elif sf > sa:
                    w += 1
                elif sf < sa:
                    l += 1
                else:
                    d += 1
        elif m.is_pre and nxt is None:
            nxt = m
    rec_txt = f"  P{w + d + l}  ·  {w}W {d}D {l}L  ·  {gf}-{ga}"
    rg.put(1, 6, rec_txt, bg(*P.bg1) + fg(*P.dim))
    if nxt:
        opp = nxt.away if (nxt.home and nxt.home.abbr == abbr) else nxt.home
        local = espn.to_local(nxt.date)
        when = local.strftime("%a %d %b · %H:%M") if local else ""
        nt = f"next: vs {opp.abbr if opp else '?'}  {when}"
        rg.put(1, rg.w - term.display_width(nt) - 2, nt, bg(*P.bg1) + fg(*P.accent2))
    rg.hline(2, 2, rg.w - 4, fg(*P.line))
    if not matches:
        center_msg(rg, 3, rg.h - 1, rg.w, "Loading team fixtures…")
        return
    r = 3
    st.sched_sel = max(0, min(st.sched_sel, len(matches) - 1))
    for i, m in enumerate(matches):
        if r >= rg.h:
            break
        row = rg.rows(r, r + 1)
        draw_compact_row(row, m, i == st.sched_sel, frame, left="date")
        row.hit(("sel", "sched_sel", i, True), 0, 2, 1, row.w - 4)
        r += 1


# ----------------------------------------------------------------------------
# help overlay
# ----------------------------------------------------------------------------

def view_help(rg, st, frame):
    bw = min(72, rg.w - 6)
    bx = (rg.w - bw) // 2
    bh = min(rg.h, 26)
    inner = rg.box(0, bx, bh, bw, style=fg(*P.accent), chars=HEAVY, title="HELP",
                   title_style=fg(*P.gold) + BOLD, fillstyle=bg(*P.bg1))
    r = 0
    inner.put(r, 1, "KEYBOARD", bg(*P.bg1) + fg(*P.accent) + BOLD); r += 1
    keys = [
        ("1-5", "switch view (Live / Schedule / Groups / Bracket / Scorers)"),
        ("Tab / Shift-Tab", "cycle views"),
        ("↑ ↓ / j k", "move selection"),
        ("← →", "schedule day · detail tabs · bracket scroll"),
        ("Enter", "open match details"),
        ("Esc", "back"),
        (":", "open command line"),
        ("r", "force refresh   ·   ? help   ·   q quit"),
    ]
    for k, d in keys:
        inner.put(r, 1, term.pad(k, 18), bg(*P.bg1) + fg(*P.gold) + BOLD)
        inner.put(r, 19, term.strip_ansi(term.truncate(d, bw - 22)), bg(*P.bg1) + fg(*P.text))
        r += 1
    r += 1
    inner.put(r, 1, "COMMANDS  (type : then…)", bg(*P.bg1) + fg(*P.accent) + BOLD); r += 1
    for c, d in S.HELP_COMMANDS:
        if r > bh - 3:
            break
        inner.put(r, 1, term.pad(c, 26), bg(*P.bg1) + fg(*P.accent2))
        inner.put(r, 27, term.strip_ansi(term.truncate(d, bw - 30)), bg(*P.bg1) + fg(*P.dim))
        r += 1


# ----------------------------------------------------------------------------
# misc
# ----------------------------------------------------------------------------

def center_msg(cv, top, bottom, cols, msg):
    widgets.center_msg(cv, top, bottom, cols, msg, fg(*P.dim) + ITALIC)


def context_label(st):
    if st.view == S.LIVE:
        n = len(st.matches_today)
        live = sum(1 for m in st.matches_today if m.is_live)
        return f"Today · {st.today_label or 'matches'} · {n} fixtures · {live} live"
    if st.view == S.SCHEDULE:
        return "Schedule · ←/→ change day · Enter for details"
    if st.view == S.GROUPS:
        return "Group Stage standings · 12 groups · green = advancing"
    if st.view == S.BRACKET:
        return "Knockout bracket · Round of 32 → Final"
    if st.view == S.SCORERS:
        return "Tournament leaders · golden boot race"
    if st.view == S.DETAIL:
        return "Match centre"
    if st.view == S.TEAM:
        return "Team fixtures & results"
    if st.view == S.HELP:
        return "Help"
    return ""


# ----------------------------------------------------------------------------
# top-level render
# ----------------------------------------------------------------------------

def render(state, cols, rows):
    st = state
    cv = Canvas(cols, rows, base())
    with st.lock:
        st.frame += 1
        frame = st.frame
        st.hits.clear()   # clickable regions track exactly this frame
        root = cv.region(hits=st.hits)
        draw_header(root.rows(0, 1), st, frame)
        draw_tabs(root.rows(1, 2), st)
        draw_context(root.rows(2, 3), st, context_label(st))
        top = 3
        bottom = rows - 3
        if bottom - top < 3:
            cv.put(rows // 2, 2, "terminal too small", fg(*P.red))
        else:
            body = root.rows(top, -2)   # rows [top .. bottom] of the screen
            v = st.view
            if v == S.LIVE:
                view_live(root.rows(top - 1, -2), st, frame)
            elif v == S.SCHEDULE:
                view_schedule(body, st, frame)
            elif v == S.GROUPS:
                view_groups(body, st, frame)
            elif v == S.BRACKET:
                view_bracket(cv, top, bottom, cols, st, frame)
            elif v == S.SCORERS:
                view_scorers(body, st, frame)
            elif v == S.DETAIL:
                view_detail(body, st, frame)
            elif v == S.TEAM:
                view_team(body, st, frame)
            elif v == S.HELP:
                view_help(body, st, frame)
        if st.command_mode:
            draw_command_palette(root, st)
        draw_statusline(root.rows(-2, -1), st)
        draw_footer(root.rows(-1), st)
    return cv.to_lines()
