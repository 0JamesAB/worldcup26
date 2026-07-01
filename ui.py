"""
ui.py - Rendering primitives and widgets built on term.py.

The core is `Canvas`: a grid of styled cells that lets views position text
absolutely (needed for the bracket and the lineup pitch) and then export
ANSI lines with adjacent same-style cells coalesced into runs.
"""

import term
from term import RESET, BOLD, DIM, fg, bg, Palette as P

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

    def fill_rect(self, r, c, h, w, style, ch=" "):
        for y in range(r, min(r + h, self.h)):
            for x in range(c, min(c + w, self.w)):
                if y < 0 or x < 0:
                    continue
                cell = self.grid[y][x]
                cell.ch = ch
                cell.style = style
                cell.cont = False

    def put(self, r, c, text, style=""):
        """Write plain `text` starting at row r, col c. Returns end column."""
        if r < 0 or r >= self.h:
            return c
        x = c
        for ch in text:
            if ch == "\n":
                break
            w = term.char_width(ch)
            if x >= self.w:
                break
            if x >= 0:
                cell = self.grid[r][x]
                cell.ch = ch
                cell.style = style
                cell.cont = False
                if w == 2 and x + 1 < self.w:
                    nxt = self.grid[r][x + 1]
                    nxt.ch = ""
                    nxt.style = style
                    nxt.cont = True
            x += w
        return x

    def put_clipped(self, r, c, text, style="", maxw=None):
        if maxw is not None:
            text = term.truncate(text, maxw, ellipsis="…") if term.display_width(text) > maxw else text
            # truncate may inject ANSI; strip for canvas safety
            text = term.strip_ansi(text)
        return self.put(r, c, text, style)

    def hline(self, r, c, length, style="", ch="─"):
        for i in range(length):
            self.put(r, c + i, ch, style)

    def vline(self, r, c, length, style="", ch="│"):
        for i in range(length):
            self.put(r + i, c, ch, style)

    def box(self, r, c, h, w, style="", chars=LIGHT, title="", title_style=None,
            fillstyle=None):
        """Draw a box at (r,c) of size h x w. Optional centered/left title."""
        if h < 2 or w < 2:
            return
        if fillstyle is not None:
            self.fill_rect(r + 1, c + 1, h - 2, w - 2, fillstyle)
        self.put(r, c, chars["tl"], style)
        self.put(r, c + w - 1, chars["tr"], style)
        self.put(r + h - 1, c, chars["bl"], style)
        self.put(r + h - 1, c + w - 1, chars["br"], style)
        self.hline(r, c + 1, w - 2, style, chars["h"])
        self.hline(r + h - 1, c + 1, w - 2, style, chars["h"])
        self.vline(r + 1, c, h - 2, style, chars["v"])
        self.vline(r + 1, c + w - 1, h - 2, style, chars["v"])
        if title:
            ts = title_style if title_style is not None else style
            t = " " + title.strip() + " "
            tx = c + 2
            self.put(r, tx, t, ts)

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

    def blit(self, other, r, c):
        """Copy another canvas onto this one at (r, c)."""
        for y in range(other.h):
            ty = r + y
            if ty < 0 or ty >= self.h:
                continue
            for x in range(other.w):
                tx = c + x
                if tx < 0 or tx >= self.w:
                    continue
                src = other.grid[y][x]
                dst = self.grid[ty][tx]
                dst.ch = src.ch
                dst.style = src.style
                dst.cont = src.cont


# ----------------------------------------------------------------------------
# Higher-level helpers used by views
# ----------------------------------------------------------------------------

def base_style():
    return bg(*P.bg0) + fg(*P.text)


def panel_style():
    return bg(*P.bg1) + fg(*P.text)


def tab_bar(cv, r, c, width, tabs, active, hint=""):
    """Render a row of tab labels. `tabs` is list of (key, label)."""
    x = c
    cv.fill_rect(r, c, 1, width, bg(*P.bg1))
    for i, (key, label) in enumerate(tabs):
        is_active = (i == active)
        if is_active:
            seg_style = bg(*P.accent) + fg(*P.bg0) + BOLD
            txt = f" {key} {label} "
        else:
            seg_style = bg(*P.bg1) + fg(*P.dim)
            txt = f" {key} {label} "
        cv.put(r, x, txt, seg_style)
        x += term.display_width(txt)
        cv.put(r, x, " ", bg(*P.bg1))
        x += 1
    if hint:
        hx = c + width - term.display_width(hint) - 1
        if hx > x:
            cv.put(r, hx, hint, bg(*P.bg1) + fg(*P.faint))


def footer(cv, r, c, width, hints, right=""):
    """Bottom key-hint bar. `hints` is list of (key, desc)."""
    cv.fill_rect(r, c, 1, width, bg(*P.bg1))
    x = c + 1
    for key, desc in hints:
        kt = f" {key} "
        cv.put(r, x, kt, bg(*P.bg2) + fg(*P.gold) + BOLD)
        x += term.display_width(kt)
        dt = f" {desc}  "
        cv.put(r, x, dt, bg(*P.bg1) + fg(*P.dim))
        x += term.display_width(dt)
    if right:
        rx = c + width - term.display_width(right) - 1
        if rx > x:
            cv.put(r, rx, right, bg(*P.bg1) + fg(*P.faint))


def center(text, width):
    return term.pad(text, width, align="center")
