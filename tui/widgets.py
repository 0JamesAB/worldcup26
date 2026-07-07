"""
widgets.py - Higher-level drawing helpers built on Canvas.

All widgets are procedural: draw_x(cv, r, c, ..., style). Colors come from
the installed theme (see theme.py) unless a `theme=` override is passed;
purely geometric helpers take explicit style strings instead.
"""

from . import term
from .canvas import Canvas, LIGHT
from .term import BOLD, fg, bg
from .theme import get_theme


def base_style(theme=None):
    t = theme or get_theme()
    return bg(*t.bg0) + fg(*t.text)


def panel_style(theme=None):
    t = theme or get_theme()
    return bg(*t.bg1) + fg(*t.text)


def tab_bar(cv, r, c, width, tabs, active, hint="", theme=None):
    """Render a row of tab labels. `tabs` is list of (key, label).

    Returns a list of (x, width) segment extents, one per tab, so callers
    can hit-test mouse clicks against the rendered labels.
    """
    t = theme or get_theme()
    x = c
    extents = []
    cv.fill_rect(r, c, 1, width, bg(*t.bg1))
    for i, (key, label) in enumerate(tabs):
        is_active = (i == active)
        if is_active:
            seg_style = bg(*t.accent) + fg(*t.bg0) + BOLD
            txt = f" {key} {label} "
        else:
            seg_style = bg(*t.bg1) + fg(*t.dim)
            txt = f" {key} {label} "
        tw = term.display_width(txt)
        # clip drawing and the recorded extent to the bar's width so
        # hit-testing never covers columns that were not rendered
        remaining = c + width - x
        if remaining <= 0:
            extents.append((x, 0))
            continue
        if tw > remaining:
            txt = term.strip_ansi(term.truncate(txt, remaining, ellipsis=""))
        cv.put(r, x, txt, seg_style)
        extents.append((x, min(term.display_width(txt), remaining)))
        x += tw
        if x < c + width:
            cv.put(r, x, " ", bg(*t.bg1))
        x += 1
    if hint:
        hx = c + width - term.display_width(hint) - 1
        if hx > x:
            cv.put(r, hx, hint, bg(*t.bg1) + fg(*t.faint))
    return extents


def footer(cv, r, c, width, hints, right="", theme=None):
    """Bottom key-hint bar. `hints` is list of (key, desc)."""
    t = theme or get_theme()
    cv.fill_rect(r, c, 1, width, bg(*t.bg1))
    x = c + 1
    for key, desc in hints:
        kt = f" {key} "
        cv.put(r, x, kt, bg(*t.bg2) + fg(*t.highlight) + BOLD)
        x += term.display_width(kt)
        dt = f" {desc}  "
        cv.put(r, x, dt, bg(*t.bg1) + fg(*t.dim))
        x += term.display_width(dt)
    if right:
        rx = c + width - term.display_width(right) - 1
        if rx > x:
            cv.put(r, rx, right, bg(*t.bg1) + fg(*t.faint))


def center(text, width):
    return term.pad(text, width, align="center")


def center_msg(cv, top, bottom, cols, msg, style=""):
    """Single-line message centered in rows [top..bottom]."""
    y = (top + bottom) // 2
    cv.put(y, max(2, (cols - term.display_width(msg)) // 2), msg, style)


def lerp_rgb(a, b, t):
    """Linear interpolation between two (r, g, b) tuples; t in [0, 1]."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_put(cv, r, c, text, c0, c1, extra=""):
    """Write `text` with a per-char fg gradient c0 -> c1 ((r,g,b) tuples).

    `extra`: style codes appended to every char (e.g. bg(...) + BOLD).
    Returns the end column (width-aware).
    """
    n = max(1, len(text) - 1)
    x = c
    for i, ch in enumerate(text):
        col = lerp_rgb(c0, c1, i / n)
        cv.put(r, x, ch, fg(*col) + extra)
        x += term.char_width(ch)
    return x


def draw_hbar(cv, r, c, width, frac, fill_style, track_style=None,
              chars=("█", "░")):
    """Horizontal meter: `frac` in [0, 1] of `width` cells.

    track_style=None skips drawing the empty portion.
    `frac` and `width` are clamped so out-of-range values never draw
    outside [c, c+width). Returns the fill cell count (callers can place
    a value after it).
    """
    width = max(0, width)
    fill = max(0, min(width, int(round(frac * width))))
    cv.put(r, c, chars[0] * fill, fill_style)
    if track_style is not None and width - fill > 0:
        cv.put(r, c + fill, chars[1] * (width - fill), track_style)
    return fill


def split_fracs(a, b):
    """Normalize two numeric-ish values ('55%', 12, 3.0) -> (fa, fb).

    Fractions sum to 1; (0.5, 0.5) on unparseable, (0, 0) on zero total.
    """
    try:
        fa = float(str(a).replace("%", ""))
        fb = float(str(b).replace("%", ""))
    except ValueError:
        return 0.5, 0.5
    tot = fa + fb
    if tot <= 0:
        return 0.0, 0.0
    return fa / tot, fb / tot


def col_layout(cols_spec, w):
    """Column extents for a draw_table cols_spec over `w` total columns.

    cols_spec: [(header, width, align)]; width=-1 marks the one flex
    column absorbing whatever the fixed columns leave over (clamped to
    zero). Returns [(x, width)] per column, x relative to the table's
    left edge.
    """
    fixed = sum(cw for _, cw, _ in cols_spec if cw >= 0)
    flexw = max(0, w - fixed)
    extents = []
    x = 0
    for _, cw, _ in cols_spec:
        cwidth = flexw if cw < 0 else cw
        extents.append((x, cwidth))
        x += cwidth
    return extents


def draw_table(cv, r, c, w, cols_spec, rows, title="", title_style="",
               rule_style="", header_style=""):
    """Compact table.

    cols_spec: [(header, width, align)]; width=-1 marks the one flex column
               absorbing leftover width; align is 'left' or 'right'.
    rows:      list of rows; each row is [(text, style), ...] matching
               cols_spec (None cells are skipped).

    Renders an optional `title` + horizontal rule, then the header row
    (skipped when no column has a header), then the data rows. Cells wider
    than their column are truncated. Returns rows consumed.
    """
    rr = r
    if title:
        cv.put(rr, c, title, title_style)
        tw = term.display_width(title)
        cv.hline(rr, c + tw + 1, max(0, w - tw - 1), rule_style, "─")
        rr += 1
    cols = col_layout(cols_spec, w)

    def cell_text(text, cwidth, align):
        text = str(text)
        if term.display_width(text) > cwidth:
            text = term.strip_ansi(term.truncate(text, cwidth))
        if align == "right":
            text = term.pad(text, cwidth, "right")
        return text

    if any(h for h, _, _ in cols_spec):
        for (hdr, _, align), (cx, cwidth) in zip(cols_spec, cols):
            if hdr:
                cv.put(rr, c + cx, cell_text(hdr, cwidth, align),
                       header_style)
        rr += 1
    for row in rows:
        for (_, _, align), (cx, cwidth), cell in zip(cols_spec, cols, row):
            if cell is None:
                continue
            text, style = cell
            cv.put(rr, c + cx, cell_text(text, cwidth, align), style)
        rr += 1
    return rr - r


def draw_card(cv, r, c, h, w, border_style="", fill_style="", chars=None,
              title="", title_style="", right="", right_style="",
              title_reserve=18, selected=False, select_style="",
              select_ch="▸"):
    """Card frame: box + left title + right-aligned text on the top border,
    plus selection chevrons in the border column when `selected`.

    `title` is truncated to keep clear of `right` (title_reserve columns).
    Returns the inner content Region (one row inside the frame, two
    columns inside each vertical border).
    """
    cv.box(r, c, h, w, style=border_style, chars=chars or LIGHT,
           fill_style=fill_style)
    if title:
        cv.put(r, c + 2,
               term.strip_ansi(term.truncate(title, w - title_reserve)),
               title_style)
    if right:
        cv.put(r, c + w - term.display_width(right) - 2, right, right_style)
    if selected:
        cv.put(r + 1, c, select_ch, select_style)
        cv.put(r + 2, c, select_ch, select_style)
    return cv.region(r + 1, c + 2, h - 2, w - 4)


def draw_duel_row(cv, r, c, width, label, lval, rval, lstyle, rstyle,
                  label_style="", track_style="", lval_style=None,
                  rval_style=None, val_w=6, gap=2, divider="▏",
                  divider_style=""):
    """Two-row, two-sided comparison bar spanning [c, c+width).

    Row r:   lval right-aligned at the left edge, label centered,
             rval left-aligned at the right edge.
    Row r+1: track with the left fill growing leftward from center in
             lstyle and the right fill growing rightward in rstyle,
             plus a divider tick at center.

    lstyle/rstyle color the bar fills (combined with track_style);
    lval_style/rval_style style the value text (default lstyle/rstyle).
    Fractions come from split_fracs(lval, rval). Returns 2 (rows used).
    """
    cv.put(r, c, term.pad(str(lval), val_w, "right"),
           lstyle if lval_style is None else lval_style)
    cv.put(r, c + width - val_w, term.pad(str(rval), val_w),
           rstyle if rval_style is None else rval_style)
    cv.put(r, c + (width - term.display_width(label)) // 2, label, label_style)
    bar_l = c + val_w + gap
    bar_r = c + width - val_w - gap
    barw = bar_r - bar_l
    mid = (bar_l + bar_r) // 2
    lf, rf = split_fracs(lval, rval)
    ln = int(round(lf * (barw // 2)))
    rn = int(round(rf * (barw // 2)))
    cv.fill_rect(r + 1, bar_l, 1, barw, track_style)
    for i in range(ln):
        cv.put(r + 1, mid - 1 - i, "█", track_style + lstyle)
    for i in range(rn):
        cv.put(r + 1, mid + i, "█", track_style + rstyle)
    cv.put(r + 1, mid, divider, track_style + divider_style)
    return 2


# ----------------------------------------------------------------------------
# Single-elimination bracket
# ----------------------------------------------------------------------------

def bracket_layout(round_sizes, feeders, unit=4, cell_w=20, col_gap=7,
                   fallback_leaves=1):
    """Geometry for a single-elimination bracket.

    round_sizes: [n0, n1, ...] slot counts per round, leaves first.
    feeders:     {(round_idx, slot): (child_a, child_b)} indices into the
                 previous round; entries and children may be None.
    fallback_leaves: leaf count assumed for sizing when round 0 is empty.

    Leaf vertical order is derived by a depth-first walk from the last
    non-empty round so real feeders sit adjacent (no crossings); unplaced
    leaves are appended in index order. Parents sit at the midpoint of
    their placed children, with a spaced fallback for parentless slots.

    Returns (width, height, colx, ypos):
      colx: [x of each round column]
      ypos: {(round_idx, slot): center row (float; round() to draw)}
    """
    nrounds = len(round_sizes)
    order, seen = [], set()

    def walk(ri, i):
        if i is None or not (0 <= i < round_sizes[ri]):
            return
        if ri == 0:
            if i not in seen:
                seen.add(i)
                order.append(i)
            return
        fa, fh = feeders.get((ri, i), (None, None))
        walk(ri - 1, fa)
        walk(ri - 1, fh)

    if round_sizes and round_sizes[-1]:
        for i in range(round_sizes[-1]):
            walk(nrounds - 1, i)
    else:
        for ri in range(nrounds - 2, 0, -1):
            if round_sizes[ri]:
                for i in range(round_sizes[ri]):
                    walk(ri, i)
                break
    for i in range(round_sizes[0] if round_sizes else 0):  # leaves the walk missed
        if i not in seen:
            seen.add(i)
            order.append(i)

    leafpos = {leaf: pos for pos, leaf in enumerate(order)}
    ypos = {(0, i): leafpos.get(i, i) * unit + 2
            for i in range(round_sizes[0] if round_sizes else 0)}
    for ri in range(1, nrounds):
        for i in range(round_sizes[ri]):
            fa, fh = feeders.get((ri, i), (None, None))
            ys = [ypos[(ri - 1, f)] for f in (fa, fh)
                  if f is not None and (ri - 1, f) in ypos]
            ypos[(ri, i)] = (sum(ys) / len(ys) if ys
                             else i * unit * (2 ** ri) + (2 ** ri))

    n0 = round_sizes[0] if round_sizes and round_sizes[0] else fallback_leaves
    height = max(1, n0) * unit + 6
    width = nrounds * (cell_w + col_gap) + 6
    colx = [2 + ri * (cell_w + col_gap) for ri in range(nrounds)]
    return width, height, colx, ypos


def draw_bracket(round_sizes, feeders, draw_cell, labels=None, label_style="",
                 connector_style="", bg_style="", unit=4, cell_w=20,
                 col_gap=7, fallback_leaves=1, canvas_cls=Canvas):
    """Build and return an oversized Canvas containing the bracket.

    Draws connectors first, then column labels (row 0), then calls
      draw_cell(cv, cy, cx, round_idx, slot)
    for every slot — the caller draws whatever it wants in a cell_w-wide
    region centered at row cy. The returned Canvas may be drawn on further
    (e.g. a consolation match) before the caller blits or scrolls it.

    Returns (canvas, colx, ypos) — see bracket_layout.
    """
    width, height, colx, ypos = bracket_layout(
        round_sizes, feeders, unit=unit, cell_w=cell_w, col_gap=col_gap,
        fallback_leaves=fallback_leaves)
    cv = canvas_cls(width, height, bg_style)

    def cy_of(ri, i):
        return int(round(ypos.get((ri, i), 2)))

    # connectors first so cell boxes overlay the line ends cleanly
    for ri in range(1, len(round_sizes)):
        cx = colx[ri]
        gutter, prev_right = cx - 3, colx[ri - 1] + cell_w - 1
        for i in range(round_sizes[ri]):
            fa, fh = feeders.get((ri, i), (None, None))
            child_ys = [cy_of(ri - 1, f) for f in (fa, fh)
                        if f is not None and (ri - 1, f) in ypos]
            if child_ys:
                draw_connector(cv, min(child_ys), max(child_ys),
                               cy_of(ri, i), prev_right, gutter, cx,
                               connector_style)

    for ri in range(len(round_sizes)):
        cx = colx[ri]
        if labels and ri < len(labels) and labels[ri]:
            cv.put(0, cx + 3, labels[ri], label_style)
        for i in range(round_sizes[ri]):
            draw_cell(cv, cy_of(ri, i), cx, ri, i)
    return cv, colx, ypos


def draw_connector(cv, c1, c2, cc, prev_right, gx, next_left, style=""):
    """Join two child cells (rows c1, c2) to a parent cell (row cc):
    stubs from each child's right edge to the gutter spine, then a tee
    out to the parent column."""
    lo, hi = min(c1, c2), max(c1, c2)
    # stubs from each child's right edge to the gutter
    for cr in (c1, c2):
        for x in range(prev_right, gx):
            cv.put(cr, x, "─", style)
    # vertical spine
    for y in range(lo, hi + 1):
        cv.put(y, gx, "│", style)
    cv.put(lo, gx, "╮", style)
    cv.put(hi, gx, "╯", style)
    # branch out to the parent (rightward), so the spine tee must open right
    cv.put(cc, gx, "├", style)
    for x in range(gx + 1, next_left):
        cv.put(cc, x, "─", style)


# ----------------------------------------------------------------------------
# Small widgets: sparkline, spinner, progress, badge, rule
# ----------------------------------------------------------------------------

SPARK_CHARS = "▁▂▃▄▅▆▇█"

SPINNER_DOTS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_LINE = "|/-\\"


def sparkline(values, lo=None, hi=None):
    """Map `values` to the 8 spark block chars scaled over [lo, hi].

    lo/hi default to min(values)/max(values); values clamp into range.
    Empty values -> ""; flat series (hi == lo) -> "▄" for every value.
    """
    if not values:
        return ""
    if lo is None:
        lo = min(values)
    if hi is None:
        hi = max(values)
    if hi == lo:
        return SPARK_CHARS[3] * len(values)
    span = hi - lo
    out = []
    for v in values:
        f = (v - lo) / span
        f = 0.0 if f < 0 else 1.0 if f > 1 else f
        out.append(SPARK_CHARS[min(7, int(f * 8))])
    return "".join(out)


def draw_sparkline(cv, r, c, values, style="", lo=None, hi=None):
    """Put a sparkline at (r, c). Returns the end column."""
    return cv.put(r, c, sparkline(values, lo, hi), style)


def spinner(frame, frames=SPINNER_DOTS):
    """Single spinner char cycling by `frame` index."""
    return frames[frame % len(frames)]


def draw_progress(cv, r, c, width, frac, fill_style, track_style=None,
                  show_pct=False, pct_style=""):
    """Progress bar built on draw_hbar.

    `frac` is clamped into [0, 1]. When show_pct, the bar occupies
    width-5 cells and the percentage is right-aligned in the last 4
    cells ("nnn%"), one space between bar and pct; if width < 5 the pct
    does not fit and is omitted, so nothing is ever drawn outside
    `width`. Returns the fill cell count.
    """
    frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    barw = max(0, width - 5) if show_pct else width
    fill = draw_hbar(cv, r, c, barw, frac, fill_style, track_style)
    if show_pct and width >= 5:
        pct = term.pad(str(int(round(frac * 100))), 3, "right") + "%"
        cv.put(r, c + barw + 1, pct, pct_style)
    return fill


def draw_badge(cv, r, c, text, style):
    """Put ' text ' (single-space padding) in `style`. Returns end column."""
    return cv.put(r, c, " " + text + " ", style)


def draw_rule(cv, r, c, width, title="", style="", title_style=None, ch="─"):
    """Horizontal rule; optional ' title ' overlaid centered on the rule.

    title_style defaults to `style`; a title wider than `width` is
    truncated via term.truncate. width <= 0 draws nothing.
    """
    if width <= 0:
        return
    cv.hline(r, c, width, style, ch)
    if title:
        t = " " + title + " "
        if term.display_width(t) > width:
            t = term.strip_ansi(term.truncate(t, width))
        tx = c + max(0, (width - term.display_width(t)) // 2)
        cv.put(r, tx, t, style if title_style is None else title_style)


# ----------------------------------------------------------------------------
# Text pane and meter rows
# ----------------------------------------------------------------------------

def draw_text_pane(cv, r, c, h, w, lines, scroll, wrap=True, style="",
                   pct=False, pct_style=""):
    """Scrolling text pane over rows [r, r+h) x cols [c, c+w).

    `lines` entries are str or (text, style) pairs; a pair's style
    replaces the default `style` for every row that entry produces.
    When `wrap`, each entry word-wraps to `w` columns via term.wrap (an
    entry may span several rows); otherwise entries render one per row,
    truncated to `w`.

    The total line count is fed into scroll.set_extent(total, h)
    (scroll: interact.ScrollState) and the slice at scroll.offset is
    drawn. When `pct` and the content overflows, the scroll position
    ("NN%") is right-aligned on the top row in pct_style. Returns the
    total (wrapped) line count.
    """
    flat = []
    for entry in lines:
        if isinstance(entry, tuple):
            text, sty = entry
        else:
            text, sty = entry, style
        if wrap:
            for seg in term.wrap(str(text), w):
                flat.append((seg, sty))
        else:
            flat.append((str(text), sty))
    total = len(flat)
    scroll.set_extent(total, h)
    y = r
    for text, sty in flat[scroll.offset:scroll.offset + max(0, h)]:
        if term.display_width(text) > w:
            text = term.strip_ansi(term.truncate(text, w))
        cv.put(y, c, text, sty)
        y += 1
    if pct and total > h:
        tag = str(scroll.pct) + "%"
        tw = term.display_width(tag)
        if tw <= w:  # never show a clipped (misleading) percentage
            cv.put(r, c + w - tw, tag, pct_style)
    return total


def draw_meter_rows(cv, r, c, w, items, label_w=None,
                    thresholds=((0.6, None), (0.8, None)), styles=None,
                    label_style="", track_style=None, show_pct=False,
                    pct_style=""):
    """Labelled meter rows: one draw_progress bar per (label, frac) item.

    label_w defaults to the widest label + 1; wider labels truncate.
    The fill style is picked per row by frac against `thresholds` --
    ascending (cutoff, style) pairs where the first cutoff the frac is
    below wins. A None pair style falls back to the matching entry of
    `styles`, a (below, mid, high) triple (one more entry than
    thresholds) whose last entry covers fracs at or above every cutoff;
    styles=None means unstyled fills. track_style/show_pct/pct_style
    pass through to draw_progress. Returns rows used.
    """
    if styles is None:
        styles = ("",) * (len(thresholds) + 1)
    if label_w is None:
        label_w = max([term.display_width(str(lb)) for lb, _ in items],
                      default=0) + 1
    rr = r
    for label, frac in items:
        fill_style = styles[len(thresholds)]
        for i, (cut, sty) in enumerate(thresholds):
            if frac < cut:
                fill_style = styles[i] if sty is None else sty
                break
        label = str(label)
        if term.display_width(label) > label_w:
            label = term.strip_ansi(term.truncate(label, label_w))
        cv.put(rr, c, label, label_style)
        draw_progress(cv, rr, c + label_w, max(0, w - label_w), frac,
                      fill_style, track_style, show_pct=show_pct,
                      pct_style=pct_style)
        rr += 1
    return rr - r
