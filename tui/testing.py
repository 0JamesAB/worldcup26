"""
testing.py - Snapshot-testing helpers for canvases.

Render a Canvas to plain text (no ANSI), mask volatile fragments (clocks,
counters) with regexes, and compare frames line-by-line.
"""

import re


def plain_lines(canvas):
    """Return canvas rows as plain strings: characters only, no ANSI."""
    lines = []
    for row in canvas.grid:
        chars = []
        for cell in row:
            if cell.cont:
                continue
            chars.append(cell.ch if cell.ch else " ")
        lines.append("".join(chars))
    return lines


def render_plain(canvas):
    """Return the whole canvas as one plain-text string."""
    return "\n".join(plain_lines(canvas))


def styled_lines(canvas):
    """Return canvas rows with ANSI styling (alias for canvas.to_lines())."""
    return canvas.to_lines()


def mask_text(s, masks):
    """Apply each (pattern, replacement) in `masks` to `s` via re.sub.

    Patterns may be compiled regexes or plain strings.
    """
    for pattern, repl in masks:
        s = re.sub(pattern, repl, s)
    return s


def _as_text(frame):
    """Normalize a frame (str or list of lines) to a single string."""
    if isinstance(frame, str):
        return frame
    return "\n".join(frame)


def frames_equal(a, b, masks=None):
    """True if two frames (each a str or list of lines) match after masking."""
    ta = _as_text(a)
    tb = _as_text(b)
    if masks:
        ta = mask_text(ta, masks)
        tb = mask_text(tb, masks)
    return ta == tb


def first_diff(a, b, masks=None):
    """First differing line after masking: (index, line_a, line_b), or None.

    If one frame is shorter, its missing lines compare as "".
    """
    ta = _as_text(a)
    tb = _as_text(b)
    if masks:
        ta = mask_text(ta, masks)
        tb = mask_text(tb, masks)
    la = ta.split("\n")
    lb = tb.split("\n")
    for i in range(max(len(la), len(lb))):
        va = la[i] if i < len(la) else ""
        vb = lb[i] if i < len(lb) else ""
        if va != vb:
            return (i, va, vb)
    return None
