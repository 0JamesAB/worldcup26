"""
term.py - Terminal control layer for the World Cup TUI.

Pure stdlib. Provides:
  - ANSI truecolor + style helpers (with graceful 256/16-color downgrade)
  - Alternate-screen / cursor / raw-input context manager
  - A non-blocking key reader that decodes escape sequences (arrows, etc.)
  - A diff-based line renderer so frames repaint without flicker

No third-party dependencies.
"""

import os
import sys
import select
import signal
import termios
import tty
from dataclasses import dataclass

# ----------------------------------------------------------------------------
# Color support detection
# ----------------------------------------------------------------------------

def _detect_color_depth():
    """Return 'truecolor', '256', or '16'."""
    if os.environ.get("NO_COLOR"):
        return "16"
    ct = os.environ.get("COLORTERM", "").lower()
    if "truecolor" in ct or "24bit" in ct:
        return "truecolor"
    term = os.environ.get("TERM", "")
    if "256" in term:
        return "256"
    # Most modern macOS/Linux terminals do truecolor; assume it unless told otherwise.
    return "truecolor"

COLOR_DEPTH = _detect_color_depth()

ESC = "\x1b"
CSI = "\x1b["


# ----------------------------------------------------------------------------
# Color helpers
# ----------------------------------------------------------------------------

def _clamp(v):
    return 0 if v < 0 else 255 if v > 255 else int(v)


def _rgb_to_256(r, g, b):
    # Map to xterm-256 color cube.
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round(((r - 8) / 247) * 24) + 232
    ri = round(r / 255 * 5)
    gi = round(g / 255 * 5)
    bi = round(b / 255 * 5)
    return 16 + 36 * ri + 6 * gi + bi


def fg(r, g, b):
    r, g, b = _clamp(r), _clamp(g), _clamp(b)
    if COLOR_DEPTH == "truecolor":
        return f"{CSI}38;2;{r};{g};{b}m"
    if COLOR_DEPTH == "256":
        return f"{CSI}38;5;{_rgb_to_256(r, g, b)}m"
    return ""


def bg(r, g, b):
    r, g, b = _clamp(r), _clamp(g), _clamp(b)
    if COLOR_DEPTH == "truecolor":
        return f"{CSI}48;2;{r};{g};{b}m"
    if COLOR_DEPTH == "256":
        return f"{CSI}48;5;{_rgb_to_256(r, g, b)}m"
    return ""


def hex_rgb(h):
    """'#rrggbb' or 'rrggbb' -> (r, g, b). Returns None on bad input."""
    if not h:
        return None
    h = h.lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def fg_hex(h, fallback=(220, 220, 220)):
    rgb = hex_rgb(h) or fallback
    return fg(*rgb)


def bg_hex(h, fallback=(20, 20, 20)):
    rgb = hex_rgb(h) or fallback
    return bg(*rgb)


# Common SGR codes
RESET = f"{CSI}0m"
BOLD = f"{CSI}1m"
DIM = f"{CSI}2m"
ITALIC = f"{CSI}3m"
UNDERLINE = f"{CSI}4m"
BLINK = f"{CSI}5m"
REVERSE = f"{CSI}7m"
NOBOLD = f"{CSI}22m"


def style(text, *codes):
    return "".join(codes) + text + RESET


# A small palette used across the app (FIFA-ish).
class Palette:
    bg0 = (12, 14, 20)        # app background
    bg1 = (20, 24, 33)        # panel background
    bg2 = (30, 36, 48)        # selected row
    line = (52, 60, 78)       # borders
    text = (223, 228, 238)    # primary text
    dim = (132, 142, 162)     # secondary text
    faint = (88, 96, 116)     # tertiary
    accent = (88, 198, 130)   # green (live / brand)
    accent2 = (120, 180, 255) # blue
    gold = (240, 196, 88)     # scorers / highlight
    red = (235, 92, 92)       # red cards / losses
    yellow = (236, 200, 92)   # yellow cards
    white = (245, 247, 252)
    live = (90, 220, 140)
    pitch = (32, 110, 64)


# ----------------------------------------------------------------------------
# Cursor / screen control
# ----------------------------------------------------------------------------

def enter_alt_screen():
    sys.stdout.write(f"{CSI}?1049h")   # alt buffer
    sys.stdout.write(f"{CSI}?25l")     # hide cursor
    sys.stdout.write(f"{CSI}2J{CSI}H") # clear + home
    sys.stdout.flush()


def exit_alt_screen():
    sys.stdout.write(f"{CSI}?25h")     # show cursor
    sys.stdout.write(f"{CSI}?1049l")   # leave alt buffer
    sys.stdout.flush()


def move(row, col):
    """1-indexed cursor move."""
    return f"{CSI}{row};{col}H"


def clear_to_eol():
    return f"{CSI}K"


def terminal_size():
    try:
        sz = os.get_terminal_size()
        return sz.columns, sz.lines
    except OSError:
        return 80, 24


# ----------------------------------------------------------------------------
# Width-aware helpers (so wide glyphs / colored strings line up)
# ----------------------------------------------------------------------------

import unicodedata
import re

_SGR_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(s):
    return _SGR_RE.sub("", s)


def char_width(ch):
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    o = ord(ch)
    # Treat common emoji blocks as width 2 (terminals usually render them wide).
    if 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or o in (0x2728, 0x2B50, 0x26BD):
        return 2
    return 1


def display_width(s):
    """Visible width of a string, ignoring ANSI codes."""
    return sum(char_width(c) for c in strip_ansi(s))


def truncate(s, width, ellipsis="…"):
    """Truncate to `width` visible columns (ANSI-aware), adding an ellipsis."""
    if display_width(s) <= width:
        return s
    out = []
    used = 0
    i = 0
    n = len(s)
    budget = max(0, width - 1)
    while i < n:
        if s[i] == "\x1b":
            m = _SGR_RE.match(s, i)
            if m:
                out.append(m.group())
                i = m.end()
                continue
        w = char_width(s[i])
        if used + w > budget:
            break
        out.append(s[i])
        used += w
        i += 1
    out.append(RESET)
    out.append(ellipsis)
    return "".join(out)


def pad(s, width, align="left", fillchar=" "):
    """Pad a (possibly colored) string to `width` visible columns."""
    w = display_width(s)
    if w >= width:
        return truncate(s, width)
    gap = width - w
    if align == "left":
        return s + fillchar * gap
    if align == "right":
        return fillchar * gap + s
    left = gap // 2
    right = gap - left
    return fillchar * left + s + fillchar * right


# ----------------------------------------------------------------------------
# Raw-input terminal context
# ----------------------------------------------------------------------------

class RawTerminal:
    """Context manager: alt-screen + cbreak raw input + cursor hidden.

    Restores the terminal on exit even if an exception propagates.
    """

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old = None
        self._resized = False

    def __enter__(self):
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        enter_alt_screen()
        try:
            signal.signal(signal.SIGWINCH, self._on_resize)
        except (ValueError, OSError):
            pass  # not in main thread / unsupported
        return self

    def __exit__(self, *exc):
        try:
            exit_alt_screen()
        finally:
            if self.old is not None:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        return False

    def _on_resize(self, *_):
        self._resized = True

    def take_resize(self):
        r, self._resized = self._resized, False
        return r


# Key constants returned by read_key
class Key:
    UP = "UP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    ENTER = "ENTER"
    ESC = "ESC"
    TAB = "TAB"
    SHIFT_TAB = "SHIFT_TAB"
    BACKSPACE = "BACKSPACE"
    HOME = "HOME"
    END = "END"
    PGUP = "PGUP"
    PGDN = "PGDN"
    DELETE = "DELETE"


def read_key(timeout=0.2):
    """Block up to `timeout` seconds for a keypress.

    Returns a Key.* constant, a single character, or None on timeout.
    Decodes the common CSI/SS3 escape sequences for arrows, etc.
    """
    fd = sys.stdin.fileno()
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return None
    ch = os.read(fd, 1)
    if not ch:
        return None
    b = ch[0]

    if b == 0x1b:  # ESC - could start a sequence
        # Peek for more bytes (very short window).
        r2, _, _ = select.select([fd], [], [], 0.02)
        if not r2:
            return Key.ESC
        seq = os.read(fd, 1)
        if seq not in (b"[", b"O"):
            return Key.ESC
        # Read the rest of the sequence.
        body = b""
        while True:
            r3, _, _ = select.select([fd], [], [], 0.02)
            if not r3:
                break
            c = os.read(fd, 1)
            body += c
            if c.isalpha() or c == b"~":
                break
        return _decode_csi(seq, body)

    if b in (0x0d, 0x0a):
        return Key.ENTER
    if b in (0x7f, 0x08):
        return Key.BACKSPACE
    if b == 0x09:
        return Key.TAB
    if b == 0x03:  # Ctrl-C
        raise KeyboardInterrupt
    if b < 0x20:
        return f"CTRL_{chr(b + 0x40)}"  # e.g. CTRL_R

    # UTF-8 multibyte: read continuation bytes.
    if b >= 0x80:
        extra = 0
        if b >= 0xf0:
            extra = 3
        elif b >= 0xe0:
            extra = 2
        elif b >= 0xc0:
            extra = 1
        buf = ch
        for _ in range(extra):
            r4, _, _ = select.select([fd], [], [], 0.01)
            if not r4:
                break
            buf += os.read(fd, 1)
        try:
            return buf.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return chr(b)


def _decode_csi(intro, body):
    text = body.decode("latin-1", "replace")
    mapping_csi = {
        "A": Key.UP, "B": Key.DOWN, "C": Key.RIGHT, "D": Key.LEFT,
        "H": Key.HOME, "F": Key.END, "Z": Key.SHIFT_TAB,
    }
    if intro == b"O" and text and text[-1] in mapping_csi:
        return mapping_csi[text[-1]]
    if text and text[-1] in mapping_csi:
        return mapping_csi[text[-1]]
    tilde = {
        "1": Key.HOME, "7": Key.HOME, "4": Key.END, "8": Key.END,
        "5": Key.PGUP, "6": Key.PGDN, "3": Key.DELETE,
    }
    if text.endswith("~"):
        num = text[:-1].split(";")[0]
        return tilde.get(num, None)
    return None


# ----------------------------------------------------------------------------
# Diff-based renderer
# ----------------------------------------------------------------------------

@dataclass
class _Frame:
    lines: list


class Renderer:
    """Holds the previous frame and repaints only changed lines."""

    def __init__(self):
        self._prev = []
        self._size = (0, 0)

    def reset(self):
        """Force a full repaint on the next render (e.g. after resize)."""
        self._prev = []
        sys.stdout.write(f"{CSI}2J")

    def render(self, lines, size):
        cols, rows = size
        if size != self._size:
            self.reset()
            self._size = size
        # Normalize to exactly `rows` lines, each padded/truncated to cols.
        frame = []
        for i in range(rows):
            raw = lines[i] if i < len(lines) else ""
            frame.append(pad(raw, cols))
        out = []
        for i, line in enumerate(frame):
            if i >= len(self._prev) or self._prev[i] != line:
                out.append(move(i + 1, 1))
                out.append(line)
                out.append(clear_to_eol())
        if out:
            sys.stdout.write("".join(out))
            sys.stdout.flush()
        self._prev = frame
