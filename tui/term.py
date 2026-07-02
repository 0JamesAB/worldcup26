"""
term.py - Terminal control layer.

Pure stdlib. Provides:
  - ANSI truecolor + style helpers (graceful 256/16-color/mono downgrade;
    'mono' is the no-color tier — NO_COLOR or TERM=dumb — where fg()/bg()
    return ''. Note: in v0.1.0 depth '16' was the no-color tier; it now
    emits real 16-color SGR codes.)
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
    """Return 'truecolor', '256', '16', or 'mono'."""
    term = os.environ.get("TERM", "")
    if os.environ.get("NO_COLOR") or term == "dumb":
        return "mono"
    ct = os.environ.get("COLORTERM", "").lower()
    if "truecolor" in ct or "24bit" in ct:
        return "truecolor"
    if "256" in term:
        return "256"
    if term in ("linux", "ansi") or term.startswith("vt"):
        return "16"
    # Most modern macOS/Linux terminals do truecolor; assume it unless told otherwise.
    return "truecolor"

COLOR_DEPTH = _detect_color_depth()


def get_color_depth():
    return COLOR_DEPTH


def set_color_depth(depth):
    """Override detection: 'truecolor', '256', '16', or 'mono'."""
    global COLOR_DEPTH
    if depth not in ("truecolor", "256", "16", "mono"):
        raise ValueError(f"bad color depth: {depth!r}")
    COLOR_DEPTH = depth


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


# Standard xterm palette for the 16 base colors.
_XTERM_16 = (
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
)


def _rgb_to_16(r, g, b):
    """Nearest of the 16 standard xterm colors (index 0-15) by squared distance."""
    best, best_d = 0, None
    for i, (pr, pg, pb) in enumerate(_XTERM_16):
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def fg(r, g, b):
    r, g, b = _clamp(r), _clamp(g), _clamp(b)
    if COLOR_DEPTH == "truecolor":
        return f"{CSI}38;2;{r};{g};{b}m"
    if COLOR_DEPTH == "256":
        return f"{CSI}38;5;{_rgb_to_256(r, g, b)}m"
    if COLOR_DEPTH == "16":
        i = _rgb_to_16(r, g, b)
        return f"{CSI}{30 + i if i < 8 else 90 + (i - 8)}m"
    return ""  # mono


def bg(r, g, b):
    r, g, b = _clamp(r), _clamp(g), _clamp(b)
    if COLOR_DEPTH == "truecolor":
        return f"{CSI}48;2;{r};{g};{b}m"
    if COLOR_DEPTH == "256":
        return f"{CSI}48;5;{_rgb_to_256(r, g, b)}m"
    if COLOR_DEPTH == "16":
        i = _rgb_to_16(r, g, b)
        return f"{CSI}{40 + i if i < 8 else 100 + (i - 8)}m"
    return ""  # mono


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


def _hard_break(word, width, lines):
    """Split `word` (ANSI-aware) at `width` columns, appending full chunks
    to `lines`. Returns the (chunk, visible_width) remainder."""
    piece = []
    used = 0
    i = 0
    n = len(word)
    while i < n:
        if word[i] == "\x1b":
            m = _SGR_RE.match(word, i)
            if m:
                piece.append(m.group())
                i = m.end()
                continue
        w = char_width(word[i])
        if used + w > width and used > 0:
            # Only flush a piece that has visible content; a glyph wider
            # than `width` itself must not leave a spurious blank line.
            lines.append("".join(piece))
            piece, used = [], 0
        piece.append(word[i])
        used += w
        i += 1
    return "".join(piece), used


def wrap(s, width):
    """ANSI-aware word wrap: split `s` on spaces into lines of at most
    `width` visible columns. SGR codes are zero-width and stay attached to
    their word; words longer than `width` are hard-broken. Returns a list
    of lines with no trailing spaces. width <= 0 returns [s] unchanged."""
    if width <= 0:
        return [s]
    lines = []
    cur = ""
    cur_w = 0
    for word in s.split(" "):
        w = display_width(word)
        if w > width:
            if cur:
                lines.append(cur.rstrip(" "))
            cur, cur_w = _hard_break(word, width, lines)
            continue
        if cur_w == 0:
            # cur is empty or all zero-width SGR codes; glue the word on so
            # a bare color code never strands alone on its own line.
            cur, cur_w = cur + word, w
        elif cur_w + 1 + w <= width:
            cur = cur + " " + word
            cur_w += 1 + w
        else:
            lines.append(cur.rstrip(" "))
            cur, cur_w = word, w
    lines.append(cur.rstrip(" "))
    return lines


# ----------------------------------------------------------------------------
# Raw-input terminal context
# ----------------------------------------------------------------------------

class RawTerminal:
    """Context manager: alt-screen + cbreak raw input + cursor hidden.

    With mouse=True, enables SGR mouse reporting (press/release + drag).
    Restores the terminal on exit even if an exception propagates.
    """

    def __init__(self, mouse=False):
        self.fd = sys.stdin.fileno()
        self.old = None
        self.mouse = mouse
        self._resized = False

    def __enter__(self):
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        enter_alt_screen()
        if self.mouse:
            self.mouse = False
            self.set_mouse(True)
        try:
            signal.signal(signal.SIGWINCH, self._on_resize)
        except (ValueError, OSError):
            pass  # not in main thread / unsupported
        return self

    def __exit__(self, *exc):
        try:
            self.set_mouse(False)
            exit_alt_screen()
        finally:
            if self.old is not None:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        return False

    def set_mouse(self, on):
        """Enable/disable SGR mouse reporting at runtime (no-op if unchanged).

        Turning it off restores the terminal's native text selection.
        """
        on = bool(on)
        if on == self.mouse:
            return
        self.mouse = on
        if on:
            sys.stdout.write(f"{CSI}?1000;1002;1006h")
        else:
            sys.stdout.write(f"{CSI}?1006;1002;1000l")
        sys.stdout.flush()

    def _on_resize(self, *_):
        self._resized = True

    def take_resize(self):
        r, self._resized = self._resized, False
        return r


class MouseEvent:
    """A decoded SGR mouse report. row/col are 0-based."""

    __slots__ = ("row", "col", "button", "kind")

    def __init__(self, row, col, button, kind):
        self.row = row
        self.col = col
        self.button = button
        self.kind = kind

    def __repr__(self):
        return (f"MouseEvent(row={self.row}, col={self.col}, "
                f"button={self.button!r}, kind={self.kind!r})")


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


def _decode_sgr_mouse(text):
    """Decode an SGR mouse body like '<0;10;5M' into a MouseEvent."""
    try:
        btn, x, y = (int(p) for p in text[1:-1].split(";"))
    except ValueError:
        return None
    final = text[-1]
    if btn & 64:
        button = "wheel_up" if btn & 1 == 0 else "wheel_down"
        kind = "wheel"
    else:
        button = {0: "left", 1: "middle", 2: "right"}.get(btn & 3)
        if btn & 32:
            kind = "motion"
        else:
            kind = "press" if final == "M" else "release"
    return MouseEvent(y - 1, x - 1, button, kind)


def _decode_csi(intro, body):
    text = body.decode("latin-1", "replace")
    if intro == b"[" and text.startswith("<") and text[-1:] in ("M", "m"):
        return _decode_sgr_mouse(text)
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
    """Holds the previous frame and repaints only changed lines.

    With sync=True, updates are wrapped in the synchronized-output mode
    (CSI ?2026) so the terminal presents each frame atomically.
    """

    def __init__(self, sync=True):
        self._prev = []
        self._size = (0, 0)
        self._sync = sync

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
            payload = "".join(out)
            if self._sync:
                payload = f"{CSI}?2026h{payload}{CSI}?2026l"
            sys.stdout.write(payload)
            sys.stdout.flush()
        self._prev = frame
