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
    """Render a row of tab labels. `tabs` is list of (key, label)."""
    t = theme or get_theme()
    x = c
    cv.fill_rect(r, c, 1, width, bg(*t.bg1))
    for i, (key, label) in enumerate(tabs):
        is_active = (i == active)
        if is_active:
            seg_style = bg(*t.accent) + fg(*t.bg0) + BOLD
            txt = f" {key} {label} "
        else:
            seg_style = bg(*t.bg1) + fg(*t.dim)
            txt = f" {key} {label} "
        cv.put(r, x, txt, seg_style)
        x += term.display_width(txt)
        cv.put(r, x, " ", bg(*t.bg1))
        x += 1
    if hint:
        hx = c + width - term.display_width(hint) - 1
        if hx > x:
            cv.put(r, hx, hint, bg(*t.bg1) + fg(*t.faint))


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
    Returns the fill cell count (callers can place a value after it).
    """
    fill = min(width, int(round(frac * width)))
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
    fixed = sum(cw for _, cw, _ in cols_spec if cw >= 0)
    flexw = max(0, w - fixed)
    xs = []
    x = c
    for _, cw, _ in cols_spec:
        xs.append(x)
        x += flexw if cw < 0 else cw

    def cell_text(text, cw, align):
        text = str(text)
        width_here = flexw if cw < 0 else cw
        if term.display_width(text) > width_here:
            text = term.strip_ansi(term.truncate(text, width_here))
        if align == "right":
            text = term.pad(text, width_here, "right")
        return text

    if any(h for h, _, _ in cols_spec):
        for (hdr, cw, align), cx in zip(cols_spec, xs):
            if hdr:
                cv.put(rr, cx, cell_text(hdr, cw, align), header_style)
        rr += 1
    for row in rows:
        for (hdr, cw, align), cx, cell in zip(cols_spec, xs, row):
            if cell is None:
                continue
            text, style = cell
            cv.put(rr, cx, cell_text(text, cw, align), style)
        rr += 1
    return rr - r


def draw_card(cv, r, c, h, w, border_style="", fill_style="", chars=None,
              title="", title_style="", right="", right_style="",
              title_reserve=18, selected=False, select_style="",
              select_ch="▸"):
    """Card frame: box + left title + right-aligned text on the top border,
    plus selection chevrons in the border column when `selected`.

    `title` is truncated to keep clear of `right` (title_reserve columns).
    Returns (r + 1, c + 2, w - 4): the inner content origin and width.
    """
    cv.box(r, c, h, w, style=border_style, chars=chars or LIGHT,
           fillstyle=fill_style)
    if title:
        cv.put(r, c + 2,
               term.strip_ansi(term.truncate(title, w - title_reserve)),
               title_style)
    if right:
        cv.put(r, c + w - term.display_width(right) - 2, right, right_style)
    if selected:
        cv.put(r + 1, c, select_ch, select_style)
        cv.put(r + 2, c, select_ch, select_style)
    return r + 1, c + 2, w - 4


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
