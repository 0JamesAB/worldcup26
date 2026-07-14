"""
theme.py - Color theme for puretui widgets.

A theme is a class with (r, g, b) tuple attributes. Subclass `Theme` to
override colors or add your own; install it once at startup with
`set_theme(MyTheme)`. Widgets accept an optional `theme=` kwarg that
defaults to the installed theme.

`presets(theme)` returns cached pre-composed ANSI strings for the canonical
combos. Strings are built bg-then-fg to stay byte-compatible with existing
app output. Mutating a Theme class in place is not supported (the cache
keys on the class); subclass and `set_theme` instead.
"""

from . import term

__all__ = ["Theme", "get_theme", "set_theme", "Styles", "presets"]


class Theme:
    """Neutral default theme. Colors are (r, g, b) tuples."""
    bg0 = (12, 14, 20)          # app background
    bg1 = (20, 24, 33)          # panel background
    bg2 = (30, 36, 48)          # selected / raised
    line = (52, 60, 78)         # borders
    text = (223, 228, 238)      # primary text
    dim = (132, 142, 162)       # secondary text
    faint = (88, 96, 116)       # tertiary
    accent = (88, 198, 130)     # primary brand
    accent2 = (120, 180, 255)   # secondary brand
    highlight = (240, 196, 88)  # key hints / emphasis
    warn = (236, 200, 92)
    error = (235, 92, 92)
    white = (245, 247, 252)


_current = Theme


def get_theme():
    return _current


def set_theme(theme):
    global _current
    _current = theme


class Styles:
    """Pre-composed ANSI strings for the canonical theme combos."""
    __slots__ = ("base", "panel", "panel_dim", "panel_faint", "panel_text_b",
                 "panel_dim_b", "panel_hl", "panel_hl_b", "raised",
                 "raised_dim", "chip", "hint")

    def __init__(self, t):
        bg, fg = term.bg, term.fg
        self.base = bg(*t.bg0) + fg(*t.text)
        self.panel = bg(*t.bg1) + fg(*t.text)
        self.panel_dim = bg(*t.bg1) + fg(*t.dim)
        self.panel_faint = bg(*t.bg1) + fg(*t.faint)
        self.panel_text_b = self.panel + term.BOLD
        self.panel_dim_b = self.panel_dim + term.BOLD
        self.panel_hl = bg(*t.bg1) + fg(*t.highlight)
        self.panel_hl_b = self.panel_hl + term.BOLD
        self.raised = bg(*t.bg2) + fg(*t.text)
        self.raised_dim = bg(*t.bg2) + fg(*t.dim)
        self.chip = bg(*t.accent) + fg(*t.bg0) + term.BOLD
        self.hint = bg(*t.bg1) + fg(*t.faint)


_STYLE_CACHE = {}


def presets(theme=None):
    """Cached `Styles` for `theme` (default: installed) at the current depth.

    Entries are keyed by (theme class, color depth), so `set_color_depth`
    naturally yields fresh strings. Do not mutate a Theme class in place;
    the cache would go stale. Subclass instead.
    """
    t = theme if theme is not None else _current
    key = (t, term.get_color_depth())
    st = _STYLE_CACHE.get(key)
    if st is None:
        st = _STYLE_CACHE[key] = Styles(t)
    return st
