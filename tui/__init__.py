"""tui - zero-dependency POSIX terminal UI toolkit.

Truecolor ANSI with 256/16-color/mono fallback, width-aware text utilities,
a styled cell-grid Canvas, raw keyboard input with escape decoding, and
a diff-based frame renderer. Pure stdlib.
"""

__version__ = "0.2.0"

from .term import (fg, bg, fg_hex, bg_hex, hex_rgb, style,
                   RESET, BOLD, DIM, ITALIC, UNDERLINE, BLINK, REVERSE,
                   strip_ansi, display_width, truncate, pad, char_width,
                   move, clear_to_eol, terminal_size,
                   get_color_depth, set_color_depth,
                   enter_alt_screen, exit_alt_screen,
                   RawTerminal, Key, read_key, Renderer,
                   wrap, MouseEvent)
from .canvas import Canvas, Cell, LIGHT, HEAVY, DOUBLE
from .theme import Theme, get_theme, set_theme
from .layout import Rect, Fixed, Flex, hsplit, vsplit
from .interact import ListState, ScrollState, HitMap
from .styles import Style
from .app import run
# `tui.style` stays the v0.1.0 term.style() helper function; the Style
# class lives in the `styles` module to keep the two names distinct.
from . import widgets, layout, interact, styles, testing
