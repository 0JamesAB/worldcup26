"""
widgets.py - Higher-level drawing helpers built on Canvas.

All widgets are procedural: draw_x(cv, r, c, ..., style). Colors come from
the installed theme (see theme.py) unless a `theme=` override is passed;
purely geometric helpers take explicit style strings instead.
"""

from . import term
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
