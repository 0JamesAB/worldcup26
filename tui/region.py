"""
region.py - Local-coordinate, clipped drawing surfaces over a Canvas.

A `Region` is a thin view of a rectangle of a Canvas (or of another
Region). It speaks the Canvas protocol in local coordinates -- (0, 0) is
the region's own top-left -- so the free widgets in widgets.py draw
through it unchanged, and it adds the ergonomics the app layer keeps
re-deriving by hand: alignment verbs, a flowing cursor, slicing and
splitting geometry, HitMap registration, a windowed blit, widget sugar,
and the interaction-integrated widgets (select_list, popup/modal,
input) that need clip, hits and state together.

The clip rectangle (own absolute rect ∩ parent clip ∩ canvas) is
precomputed at construction and threaded into every Canvas primitive:
nothing a Region draws can escape it, and an empty clip makes every
operation a no-op. Regions expose no `.grid` and no `to_lines()` -- the
Canvas stays the single owner of cells and export.

Styles may be raw ANSI strings or Style objects; they are normalized to
strings exactly once, at the Region boundary (Canvas stays str-only).
`region.style` is used only as the fill() default and is inherited by
child Regions; it is never merged into text styles.
"""

from . import term, widgets
from .canvas import LIGHT
from .layout import Rect, hsplit, vsplit


def _sty(s, default=""):
    """Normalize a style (None, str, or Style) to an ANSI prefix string."""
    if s is None:
        return default
    if type(s) is str:
        return s
    return str(s)


def _sty_kwargs(kw):
    """Normalize every non-None *style keyword in `kw` in place."""
    for k in kw:
        if k.endswith("style") and kw[k] is not None:
            kw[k] = _sty(kw[k])
    return kw


def _fit(text, width):
    """Ellipsis-truncate `text` to `width` columns, ANSI-stripped."""
    if term.display_width(text) > width:
        text = term.strip_ansi(term.truncate(text, width, ellipsis="…"))
    return text


class Region:
    """A clipped, local-coordinate view of a Canvas rectangle."""

    __slots__ = ("_cv", "_r", "_c", "h", "w", "_clip", "hits", "style",
                 "_row", "_col")

    def __init__(self, parent, r=0, c=0, h=None, w=None, hits=None,
                 style=None):
        """View rows [r, r+h) x cols [c, c+w) of `parent` (Canvas or
        Region, coords local to it). h/w None run to the parent's edge;
        hits/style default to the parent's when it is a Region."""
        if isinstance(parent, Region):
            cv = parent._cv
            base_r, base_c = parent._r, parent._c
            ph, pw = parent.h, parent.w
            pclip = parent._clip
            if hits is None:
                hits = parent.hits
            if style is None:
                style = parent.style
        else:
            cv = parent
            base_r = base_c = 0
            ph, pw = cv.h, cv.w
            pclip = (0, 0, cv.h, cv.w)
        if h is None:
            h = ph - r
        if w is None:
            w = pw - c
        self._cv = cv
        self._r = base_r + r
        self._c = base_c + c
        self.h = max(0, h)
        self.w = max(0, w)
        self.hits = hits
        self.style = _sty(style)
        y0 = max(self._r, pclip[0], 0)
        x0 = max(self._c, pclip[1], 0)
        y1 = min(self._r + self.h, pclip[2], cv.h)
        x1 = min(self._c + self.w, pclip[3], cv.w)
        self._clip = (y0, x0, max(y0, y1), max(x0, x1))
        self._row = 0
        self._col = 0

    def __repr__(self):
        return (f"Region(r={self._r}, c={self._c}, "
                f"h={self.h}, w={self.w})")

    # -- Canvas protocol (local coordinates) ---------------------------------

    def put(self, r, c, text, style="", *, max_w=None):
        """Write plain `text` at local (r, c). Returns the local end col.

        max_w fits the text into that many columns (ellipsis-truncated).
        """
        if max_w is not None:
            text = _fit(text, max_w)
        return self._cv.put(self._r + r, self._c + c, text, _sty(style),
                            clip=self._clip) - self._c

    def put_clipped(self, r, c, text, style="", *, max_w=None):
        """Canvas-protocol alias for put(..., max_w=max_w)."""
        return self.put(r, c, text, style, max_w=max_w)

    def fill_rect(self, r, c, h, w, style, ch=" "):
        self._cv.fill_rect(self._r + r, self._c + c, h, w, _sty(style), ch,
                           clip=self._clip)

    def fill(self, style=None):
        """Fill the whole region; `style` defaults to region.style."""
        self._cv.fill_rect(self._r, self._c, self.h, self.w,
                           self.style if style is None else _sty(style),
                           clip=self._clip)

    def hline(self, r, c, length=None, style="", ch="─"):
        """Horizontal line; length None runs to the right edge."""
        if length is None:
            length = self.w - c
        self._cv.hline(self._r + r, self._c + c, length, _sty(style), ch,
                       clip=self._clip)

    def vline(self, r, c, length=None, style="", ch="│"):
        """Vertical line; length None runs to the bottom edge."""
        if length is None:
            length = self.h - r
        self._cv.vline(self._r + r, self._c + c, length, _sty(style), ch,
                       clip=self._clip)

    def box(self, r=0, c=0, h=None, w=None, style="", chars=LIGHT, title="",
            title_style=None, fill_style=None):
        """Draw a box (whole region by default). Returns the inner Region."""
        if h is None:
            h = self.h - r
        if w is None:
            w = self.w - c
        self._cv.box(self._r + r, self._c + c, h, w, style=_sty(style),
                     chars=chars, title=title,
                     title_style=(None if title_style is None
                                  else _sty(title_style)),
                     fill_style=None if fill_style is None else _sty(fill_style),
                     clip=self._clip)
        return Region(self, r + 1, c + 1, max(0, h - 2), max(0, w - 2))

    # -- alignment verbs ------------------------------------------------------

    def left(self, text, style="", r=0, pad=0):
        """Left-align `text` at column `pad` on row `r`. Returns the local
        end col."""
        avail = self.w - pad
        if avail <= 0:
            return pad
        return self.put(r, pad, _fit(text, avail), style)

    def right(self, text, style="", r=0, pad=0):
        """Right-align `text` on row `r`, `pad` cols in from the right edge.
        Returns the local start col."""
        avail = self.w - pad
        if avail <= 0:
            return max(0, avail)
        text = _fit(text, avail)
        x = max(0, self.w - pad - term.display_width(text))
        self.put(r, x, text, style)
        return x

    def center(self, text, style="", r=0, pad=0):
        """Center `text` on row `r` between `pad` insets. Returns the local
        start col."""
        avail = self.w - 2 * pad
        if avail <= 0:
            return pad
        text = _fit(text, avail)
        x = pad + max(0, (avail - term.display_width(text)) // 2)
        self.put(r, x, text, style)
        return x

    # -- cursor ---------------------------------------------------------------

    def at(self, r, c=0):
        """Move the cursor to local (r, c). Chainable."""
        self._row = r
        self._col = c
        return self

    def write(self, text, style="", max_w=None):
        """Write at the cursor and advance it. Chainable."""
        self._col = self.put(self._row, self._col, text, style, max_w=max_w)
        return self

    def gap(self, n=1):
        """Advance the cursor `n` columns. Chainable."""
        self._col += n
        return self

    def ln(self, n=1):
        """Move the cursor down `n` rows, back to column 0. Chainable."""
        self._row += n
        self._col = 0
        return self

    # -- geometry ---------------------------------------------------------------

    def region(self, r=0, c=0, h=None, w=None, hits=None, style=None):
        """Child Region in local coords (None sizes run to the edge)."""
        return Region(self, r, c, h, w, hits=hits, style=style)

    sub = region

    def rows(self, a=0, b=None):
        """Region over local rows [a:b] (slice semantics, negatives ok)."""
        start, stop, _ = slice(a, b).indices(self.h)
        return Region(self, start, 0, max(0, stop - start), self.w)

    def cols(self, a=0, b=None):
        """Region over local cols [a:b] (slice semantics, negatives ok)."""
        start, stop, _ = slice(a, b).indices(self.w)
        return Region(self, 0, start, self.h, max(0, stop - start))

    def inset(self, dr, dc=None):
        """Region shrunk by dr rows top+bottom and dc cols left+right.

        dc defaults to dr. Size clamps to non-negative.
        """
        if dc is None:
            dc = dr
        return Region(self, dr, dc,
                      max(0, self.h - 2 * dr), max(0, self.w - 2 * dc))

    def split_v(self, *specs, gap=0):
        """Stacked child Regions via layout.vsplit over the local rect."""
        return [Region(self, rc.r, rc.c, rc.h, rc.w)
                for rc in vsplit(Rect(0, 0, self.h, self.w), *specs, gap=gap)]

    def split_h(self, *specs, gap=0):
        """Side-by-side child Regions via layout.hsplit over the local rect."""
        return [Region(self, rc.r, rc.c, rc.h, rc.w)
                for rc in hsplit(Rect(0, 0, self.h, self.w), *specs, gap=gap)]

    @property
    def rect(self):
        """The region's absolute rectangle in canvas coordinates."""
        return Rect(self._r, self._c, self.h, self.w)

    # -- interaction & blit -----------------------------------------------------

    def hit(self, action, r=0, c=0, h=None, w=None):
        """Register the local rect (whole region by default), clipped to
        what is actually visible, as `action` in the inherited HitMap.
        No-op when the Region has no HitMap or nothing is visible."""
        if self.hits is None:
            return
        if h is None:
            h = self.h - r
        if w is None:
            w = self.w - c
        y0 = max(self._r + r, self._clip[0])
        x0 = max(self._c + c, self._clip[1])
        y1 = min(self._r + r + h, self._clip[2])
        x1 = min(self._c + c + w, self._clip[3])
        if y1 > y0 and x1 > x0:
            self.hits.add(y0, x0, y1 - y0, x1 - x0, action)

    def blit(self, src, r=0, c=0, *, src_r=0, src_c=0):
        """Blit a window of Canvas `src` (from source offset (src_r, src_c))
        at local (r, c). The window covers the rest of this region from
        (r, c) — i.e. h-r rows by w-c cols. The Canvas blit repairs
        wide-glyph tears at the window edges."""
        self._cv.blit(src, self._r + r, self._c + c, src_r=src_r,
                      src_c=src_c, h=max(0, self.h - r),
                      w=max(0, self.w - c), clip=self._clip)

    # -- widget sugar (delegates to the free widgets.draw_* functions) ----------

    def card(self, r=0, c=0, h=None, w=None, **kw):
        """draw_card over the local rect. Returns the inner content Region."""
        if h is None:
            h = self.h - r
        if w is None:
            w = self.w - c
        return widgets.draw_card(self, r, c, h, w, **_sty_kwargs(kw))

    def table(self, cols_spec, rows, r=0, c=0, w=None, **kw):
        """draw_table at local (r, c). Returns rows consumed."""
        if w is None:
            w = self.w - c
        return widgets.draw_table(self, r, c, w, cols_spec, rows,
                                  **_sty_kwargs(kw))

    def tab_bar(self, tabs, active, r=0, c=0, w=None, hint="", theme=None):
        """widgets.tab_bar at local (r, c). Returns local (x, w) extents."""
        if w is None:
            w = self.w - c
        return widgets.tab_bar(self, r, c, w, tabs, active, hint=hint,
                               theme=theme)

    def rule(self, r=0, c=0, w=None, **kw):
        """draw_rule spanning to the right edge by default."""
        if w is None:
            w = self.w - c
        return widgets.draw_rule(self, r, c, w, **_sty_kwargs(kw))

    def duel(self, label, lval, rval, lstyle, rstyle, r=0, c=0, w=None, **kw):
        """draw_duel_row over the local width. Returns rows used (2)."""
        if w is None:
            w = self.w - c
        return widgets.draw_duel_row(self, r, c, w, label, lval, rval,
                                     _sty(lstyle), _sty(rstyle),
                                     **_sty_kwargs(kw))

    def hbar(self, frac, fill_style, r=0, c=0, w=None, **kw):
        """draw_hbar over the local width. Returns the fill cell count."""
        if w is None:
            w = self.w - c
        return widgets.draw_hbar(self, r, c, w, frac, _sty(fill_style),
                                 **_sty_kwargs(kw))

    def progress(self, frac, fill_style, r=0, c=0, w=None, **kw):
        """draw_progress over the local width. Returns the fill cell count."""
        if w is None:
            w = self.w - c
        return widgets.draw_progress(self, r, c, w, frac, _sty(fill_style),
                                     **_sty_kwargs(kw))

    def badge(self, text, style, r=0, c=0):
        """draw_badge at local (r, c). Returns the local end col."""
        return widgets.draw_badge(self, r, c, text, _sty(style))

    def spark(self, values, r=0, c=0, style="", lo=None, hi=None):
        """draw_sparkline at local (r, c). Returns the local end col."""
        return widgets.draw_sparkline(self, r, c, values, _sty(style), lo, hi)

    def gradient(self, text, c0, c1, r=0, c=0, extra=""):
        """gradient_put at local (r, c). Returns the local end col."""
        return widgets.gradient_put(self, r, c, text, c0, c1, _sty(extra))

    def text_pane(self, lines, scroll, r=0, c=0, h=None, w=None, **kw):
        """draw_text_pane over the local rect. Returns the total
        (wrapped) line count."""
        if h is None:
            h = self.h - r
        if w is None:
            w = self.w - c
        return widgets.draw_text_pane(self, r, c, h, w, lines, scroll,
                                      **_sty_kwargs(kw))

    def meter_rows(self, items, r=0, c=0, w=None, **kw):
        """draw_meter_rows over the local width. Returns rows used."""
        if w is None:
            w = self.w - c
        return widgets.draw_meter_rows(self, r, c, w, items,
                                       **_sty_kwargs(kw))

    # -- interaction-integrated widgets (clip + hits + state together) ----------

    def select_list(self, items, state, draw_item, item_h=1, on_open=None,
                    counter=None):
        """Windowed selectable list with integrated click handling.

        `state` is an interact.ListState; its count is synced to
        len(items) first. Each visible item is painted by
        draw_item(item_region, item, i, selected) into its own
        full-width Region of item_h rows; item_h may be a callable
        (item) -> rows for variable-height items. Windowing is the
        run-fit algorithm: advance the window start until the run
        start..sel fits the region height, always draw the first
        windowed item (clipped when oversized), and drop rather than
        clip later items. For uniform item_h this degrades to the
        simple bottom-anchored window. Every visible item registers a
        click hit: clicking selects it, and clicking the already
        selected item calls on_open(item, i) when given. When items
        overflow, counter(start, stop, count) is called so the caller
        can draw its own indicator. Returns the visible (start, stop)
        slice.
        """
        count = len(items)
        state.set_count(count)
        if count == 0 or self.h <= 0:
            return (0, 0)
        sel = state.sel
        if callable(item_h):
            heights = [item_h(it) for it in items]
            start = 0
            # advance `start` until the run start..sel fits; running sum O(n)
            used = sum(heights[:sel + 1])
            while start < sel and used > self.h:
                used -= heights[start]
                start += 1
        else:
            heights = None
            # uniform heights: the run-fit window closes to arithmetic
            fit = self.h // item_h if item_h > 0 else count
            start = min(sel, max(0, sel + 1 - fit))
        r = 0
        stop = start
        for i in range(start, count):
            rows_i = heights[i] if heights is not None else item_h
            # keep whole items (but always draw the first)
            if i > start and r + rows_i > self.h:
                break
            item_rg = self.sub(r, 0, rows_i, self.w)
            draw_item(item_rg, items[i], i, i == sel)

            if self.hits is not None:
                def click(i=i, item=items[i]):
                    if i == state.sel and on_open is not None:
                        on_open(item, i)
                    state.sel = i

                item_rg.hit(click)
            r += rows_i
            stop = i + 1
        if counter is not None and stop - start < count:
            counter(start, stop, count)
        return (start, stop)

    def popup(self, r, c, h, w, title="", style="", fill_style=None,
              chars=None):
        """Overlay box at local (r, c): border, opaque fill, and a
        click-swallowing hit over the whole rect so hits drawn under
        the overlay are dead. fill_style defaults to region.style,
        chars to LIGHT. Content hits registered afterwards (inside the
        returned inner Region) win the overlap. Returns the inner
        content Region."""
        inner = self.box(r, c, h, w, style=style,
                         chars=LIGHT if chars is None else chars, title=title,
                         fill_style=(self.style if fill_style is None
                                     else _sty(fill_style)))
        if self.hits is not None:
            self.hit(lambda: None, r, c, h, w)
        return inner

    def modal(self, h, w, **kw):
        """An h x w popup centered in the region. Returns the inner
        content Region."""
        return self.popup(max(0, (self.h - h) // 2),
                          max(0, (self.w - w) // 2), h, w, **kw)

    def input(self, edit, prompt="", style="", cursor_style=None, ghost="",
              r=0):
        """A one-line text input on row `r`: prompt, the edit buffer
        with a block cursor at edit.cursor, and an optional dim `ghost`
        completion after the text. `edit` is anything with .text and
        .cursor (interact.LineEdit); key handling stays on it -- this
        only draws. The buffer scrolls horizontally to keep the cursor
        visible; column math assumes single-width characters.
        cursor_style defaults to `style` + REVERSE. Returns the
        cursor's local column."""
        style = _sty(style)
        if cursor_style is None:
            cursor_style = style + term.REVERSE
        else:
            cursor_style = _sty(cursor_style)
        c = self.put(r, 0, prompt, style) if prompt else 0
        avail = self.w - c
        if avail <= 0:
            return c
        text = edit.text
        cur = max(0, min(edit.cursor, len(text)))
        off = cur - avail + 1 if cur >= avail else 0
        vis = text[off:off + avail]
        self.put(r, c, vis, style)
        tail = c + len(vis)
        if ghost and off + len(vis) == len(text) and tail < self.w:
            self.put(r, tail, ghost, style + term.DIM, max_w=self.w - tail)
        cx = c + cur - off
        if cur < len(text):
            ch = text[cur]
        elif ghost:
            ch = ghost[0]
        else:
            ch = " "
        self.put(r, cx, ch, cursor_style)
        return cx
