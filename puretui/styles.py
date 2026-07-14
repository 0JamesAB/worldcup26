"""
styles.py - Composable Style objects over the raw ANSI-string idiom.

Raw ANSI strings (term.fg(...) + term.BOLD) stay first-class; Style is
sugar for the places where readability wins:

    err = Style(fg="#eb5c5c").bold()
    print(err("boom"))                    # colored, bold, RESET-terminated
    hot = err.on((40, 12, 12))            # same fg/attrs, new bg
    merged = base + err                   # err's colors win, attrs union

Styles are immutable value objects: the chainable methods return new
instances, and equal styles hash equal. Rendering delegates to the term
color helpers, so the current color depth is respected (colors vanish at
mono depth; attributes remain).
"""

from . import term

__all__ = ["Style"]

_ATTRS = ("bold", "dim", "italic", "underline", "reverse", "blink")
_ATTR_CODES = {
    "bold": term.BOLD,
    "dim": term.DIM,
    "italic": term.ITALIC,
    "underline": term.UNDERLINE,
    "reverse": term.REVERSE,
    "blink": term.BLINK,
}


def _coerce_color(color):
    """Normalize a color spec to an (r, g, b) tuple or None.

    Accepts an (r, g, b) sequence or a hex string ('#rrggbb', 'rrggbb',
    or shorthand 'rgb'). Invalid hex or a sequence that is not exactly
    three components raises ValueError, matching the eager attr check.
    """
    if color is None:
        return None
    if isinstance(color, str):
        rgb = term.hex_rgb(color)
        if rgb is None:
            raise ValueError(f"bad hex color: {color!r}")
        return rgb
    rgb = tuple(color)
    if len(rgb) != 3:
        raise ValueError(f"bad color (need 3 components): {color!r}")
    return rgb


class Style:
    """An immutable fg/bg/attribute bundle that renders to an ANSI prefix.

    fg/bg accept an (r, g, b) sequence, a hex string, or None; invalid
    colors and unknown attrs raise ValueError at construction time.
    """

    __slots__ = ("fg", "bg", "attrs")

    def __init__(self, fg=None, bg=None, attrs=()):
        self.fg = _coerce_color(fg)
        self.bg = _coerce_color(bg)
        attrs = frozenset(attrs)
        bad = attrs - frozenset(_ATTRS)
        if bad:
            raise ValueError(f"unknown attrs: {sorted(bad)!r}")
        self.attrs = attrs

    # -- chainable copies ----------------------------------------------------

    def _with_attr(self, name):
        return Style(fg=self.fg, bg=self.bg, attrs=self.attrs | {name})

    def bold(self):
        return self._with_attr("bold")

    def dim(self):
        return self._with_attr("dim")

    def italic(self):
        return self._with_attr("italic")

    def underline(self):
        return self._with_attr("underline")

    def reverse(self):
        return self._with_attr("reverse")

    def blink(self):
        return self._with_attr("blink")

    def on(self, bg):
        """New Style with the background replaced."""
        return Style(fg=self.fg, bg=bg, attrs=self.attrs)

    # -- composition ---------------------------------------------------------

    def __add__(self, other):
        """Merge: other's fg/bg win when set; attrs union."""
        if not isinstance(other, Style):
            return NotImplemented
        return Style(fg=other.fg if other.fg is not None else self.fg,
                     bg=other.bg if other.bg is not None else self.bg,
                     attrs=self.attrs | other.attrs)

    __or__ = __add__

    # -- rendering -----------------------------------------------------------

    def __str__(self):
        """ANSI prefix at the current color depth (colors drop at mono)."""
        parts = []
        if self.fg is not None:
            parts.append(term.fg(*self.fg))
        if self.bg is not None:
            parts.append(term.bg(*self.bg))
        for name in _ATTRS:
            if name in self.attrs:
                parts.append(_ATTR_CODES[name])
        return "".join(parts)

    def __call__(self, text):
        """Wrap `text` in this style, terminated with RESET."""
        return str(self) + text + term.RESET

    # -- value semantics -----------------------------------------------------

    def __eq__(self, other):
        if not isinstance(other, Style):
            return NotImplemented
        return (self.fg == other.fg and self.bg == other.bg
                and self.attrs == other.attrs)

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    def __hash__(self):
        return hash((self.fg, self.bg, self.attrs))

    def __repr__(self):
        return (f"Style(fg={self.fg!r}, bg={self.bg!r}, "
                f"attrs={tuple(sorted(self.attrs))!r})")
