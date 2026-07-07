"""
canvas.py - Rendering primitives built on term.py.

The core is `Canvas`: a grid of styled cells that lets callers position text
absolutely and then export ANSI lines with adjacent same-style cells
coalesced into runs.
"""

from . import term
from .term import RESET

# Box-drawing sets
LIGHT = dict(tl="╭", tr="╮", bl="╰", br="╯", h="─", v="│",
             lt="├", rt="┤", tt="┬", bt="┴", x="┼")
HEAVY = dict(tl="┏", tr="┓", bl="┗", br="┛", h="━", v="┃",
             lt="┣", rt="┫", tt="┳", bt="┻", x="╋")
DOUBLE = dict(tl="╔", tr="╗", bl="╚", br="╝", h="═", v="║",
              lt="╠", rt="╣", tt="╦", bt="╩", x="╬")


class Cell:
    __slots__ = ("ch", "style", "cont")

    def __init__(self, ch=" ", style=""):
        self.ch = ch
        self.style = style
        self.cont = False  # True if this cell is the 2nd half of a wide glyph


class Canvas:
    """A styled character grid. (0,0) is top-left.

    put()/text() write *plain* text (no embedded ANSI) plus a style string
    (ANSI prefixes like fg(...)+BOLD). to_lines() coalesces runs.
    """

    def __init__(self, width, height, bg_style=""):
        self.w = max(1, width)
        self.h = max(1, height)
        self.bg = bg_style
        self.grid = [[Cell(" ", bg_style) for _ in range(self.w)]
                     for _ in range(self.h)]

    def fill(self, style):
        for row in self.grid:
            for c in row:
                c.ch = " "
                c.style = style
                c.cont = False

    def fill_rect(self, r, c, h, w, style, ch=" ", clip=None):
        if clip is None:
            clip = (0, 0, self.h, self.w)
        ya = max(r, clip[0])
        yb = min(r + h, clip[2])
        xa = max(c, clip[1])
        xb = min(c + w, clip[3])
        for y in range(ya, yb):
            row = self.grid[y]
            for x in range(xa, xb):
                cell = row[x]
                cell.ch = ch
                cell.style = style
                cell.cont = False

    def put(self, r, c, text, style="", *, clip=None):
        """Write plain `text` starting at row r, col c. Returns end column.

        `clip` is a (y0, x0, y1, x1) half-open rect in canvas coords, already
        intersected with the canvas by the caller. A wide glyph straddling an
        interior clip edge is dropped whole; at the canvas edge the legacy
        lead-only write is preserved.
        """
        if clip is None:
            clip = (0, 0, self.h, self.w)
        y0, x0, y1, x1 = clip
        if r < y0 or r >= y1:
            return c
        row = self.grid[r]
        char_width = term.char_width
        x = c
        for ch in text:
            if ch == "\n":
                break
            w = char_width(ch)
            if x >= x1:
                break
            if x >= x0:
                if w == 2 and x + 1 >= x1 and x1 < self.w:
                    break  # would straddle an interior clip edge: drop whole
                cell = row[x]
                cell.ch = ch
                cell.style = style
                cell.cont = False
                if w == 2 and x + 1 < x1:
                    nxt = row[x + 1]
                    nxt.ch = ""
                    nxt.style = style
                    nxt.cont = True
            x += w
        return x

    def put_clipped(self, r, c, text, style="", *, max_w=None, clip=None):
        if max_w is not None:
            text = term.truncate(text, max_w, ellipsis="…") if term.display_width(text) > max_w else text
            # truncate may inject ANSI; strip for canvas safety
            text = term.strip_ansi(text)
        return self.put(r, c, text, style, clip=clip)

    def hline(self, r, c, length, style="", ch="─", clip=None):
        if term.char_width(ch) == 1:
            self.put(r, c, ch * length, style, clip=clip)
            return
        for i in range(length):
            self.put(r, c + i, ch, style, clip=clip)

    def vline(self, r, c, length, style="", ch="│", clip=None):
        for i in range(length):
            self.put(r + i, c, ch, style, clip=clip)

    def box(self, r, c, h, w, style="", chars=LIGHT, title="", title_style=None,
            fill_style=None, clip=None):
        """Draw a box at (r,c) of size h x w. Optional centered/left title."""
        if h < 2 or w < 2:
            return
        if fill_style is not None:
            self.fill_rect(r + 1, c + 1, h - 2, w - 2, fill_style, clip=clip)
        self.put(r, c, chars["tl"], style, clip=clip)
        self.put(r, c + w - 1, chars["tr"], style, clip=clip)
        self.put(r + h - 1, c, chars["bl"], style, clip=clip)
        self.put(r + h - 1, c + w - 1, chars["br"], style, clip=clip)
        self.hline(r, c + 1, w - 2, style, chars["h"], clip=clip)
        self.hline(r + h - 1, c + 1, w - 2, style, chars["h"], clip=clip)
        self.vline(r + 1, c, h - 2, style, chars["v"], clip=clip)
        self.vline(r + 1, c + w - 1, h - 2, style, chars["v"], clip=clip)
        if title:
            ts = title_style if title_style is not None else style
            t = " " + title.strip() + " "
            tx = c + 2
            self.put(r, tx, t, ts, clip=clip)

    def to_lines(self):
        lines = []
        for row in self.grid:
            parts = []
            cur_style = None
            for cell in row:
                if cell.cont:
                    continue
                if cell.style != cur_style:
                    parts.append(RESET)
                    if cell.style:
                        parts.append(cell.style)
                    cur_style = cell.style
                parts.append(cell.ch if cell.ch else " ")
            parts.append(RESET)
            lines.append("".join(parts))
        return lines

    def blit(self, other, r, c, src_r=0, src_c=0, h=None, w=None, clip=None):
        """Copy a window of another canvas onto this one at (r, c).

        (src_r, src_c, h, w) select the source window (defaults: the rest of
        `other`). Wide-glyph tears at the window edges are repaired: a leading
        orphan continuation cell, or a wide lead whose continuation falls
        outside the window, becomes a space in the source cell's style.
        """
        if h is None:
            h = other.h - src_r
        if w is None:
            w = other.w - src_c
        if clip is None:
            clip = (0, 0, self.h, self.w)
        y0, x0, y1, x1 = clip
        ya = max(src_r, 0)
        yb = min(src_r + h, other.h)
        xa = max(src_c, 0)
        xb = min(src_c + w, other.w)
        for y in range(ya, yb):
            ty = r + y - src_r
            if ty < y0 or ty >= y1:
                continue
            srow = other.grid[y]
            drow = self.grid[ty]
            for x in range(xa, xb):
                tx = c + x - src_c
                if tx < x0 or tx >= x1:
                    continue
                src = srow[x]
                ch = src.ch
                cont = src.cont
                if cont:
                    if x == xa or tx == x0:
                        # orphan continuation: its lead fell outside the
                        # source window or the destination clip
                        ch = " "
                        cont = False
                elif ch and term.char_width(ch) == 2:
                    # will the continuation cell actually be written?
                    will_cont = (x + 1 < xb and srow[x + 1].cont
                                 and tx + 1 < x1)
                    if not will_cont and (tx + 1 < x1 or x1 < self.w):
                        # continuation lost at an interior edge (dest clip,
                        # source window, or a legacy source-edge lead):
                        # repair to a space. At the destination canvas edge
                        # keep the legacy lead-only write, matching put().
                        ch = " "
                dst = drow[tx]
                dst.ch = ch
                dst.style = src.style
                dst.cont = cont

    def region(self, r=0, c=0, h=None, w=None, hits=None, style=None):
        """Create a Region viewing a rectangle of this canvas."""
        from .region import Region
        return Region(self, r, c, h, w, hits=hits, style=style)
