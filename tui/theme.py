"""
theme.py - Color theme for tui widgets.

A theme is a class with (r, g, b) tuple attributes. Subclass `Theme` to
override colors or add your own; install it once at startup with
`set_theme(MyTheme)`. Widgets accept an optional `theme=` kwarg that
defaults to the installed theme.
"""


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
