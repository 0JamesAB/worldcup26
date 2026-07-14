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

import base64
import functools
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
    """Override detection: 'truecolor', '256', '16', or 'mono'.

    This is the required mutation path for COLOR_DEPTH: it also clears the
    fg()/bg() result caches, which are keyed by (r, g, b) only and so are
    valid for exactly one depth. Assigning term.COLOR_DEPTH directly would
    leave stale entries behind.
    """
    global COLOR_DEPTH
    if depth not in ("truecolor", "256", "16", "mono"):
        raise ValueError(f"bad color depth: {depth!r}")
    COLOR_DEPTH = depth
    _FG_CACHE.clear()
    _BG_CACHE.clear()


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


# Result-interning caches for fg()/bg(), keyed by clamped (r, g, b).
#
# These are explicit dicts cleared by set_color_depth() rather than an
# lru_cache on fg/bg themselves: an lru_cache would key only on the rgb
# arguments, so entries formatted under one COLOR_DEPTH would be served
# verbatim after the depth changed (unless depth were threaded through as
# an extra argument at every call site). The explicit-dict route keeps the
# public fg(r, g, b) signature and makes the invalidation point obvious.
_FG_CACHE = {}
_BG_CACHE = {}


def fg(r, g, b):
    r, g, b = _clamp(r), _clamp(g), _clamp(b)
    key = (r, g, b)
    s = _FG_CACHE.get(key)
    if s is not None:
        return s
    if COLOR_DEPTH == "truecolor":
        s = f"{CSI}38;2;{r};{g};{b}m"
    elif COLOR_DEPTH == "256":
        s = f"{CSI}38;5;{_rgb_to_256(r, g, b)}m"
    elif COLOR_DEPTH == "16":
        i = _rgb_to_16(r, g, b)
        s = f"{CSI}{30 + i if i < 8 else 90 + (i - 8)}m"
    else:
        s = ""  # mono
    _FG_CACHE[key] = s
    return s


def bg(r, g, b):
    r, g, b = _clamp(r), _clamp(g), _clamp(b)
    key = (r, g, b)
    s = _BG_CACHE.get(key)
    if s is not None:
        return s
    if COLOR_DEPTH == "truecolor":
        s = f"{CSI}48;2;{r};{g};{b}m"
    elif COLOR_DEPTH == "256":
        s = f"{CSI}48;5;{_rgb_to_256(r, g, b)}m"
    elif COLOR_DEPTH == "16":
        i = _rgb_to_16(r, g, b)
        s = f"{CSI}{40 + i if i < 8 else 100 + (i - 8)}m"
    else:
        s = ""  # mono
    _BG_CACHE[key] = s
    return s


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


def set_title(s):
    """Set the terminal window title (OSC 2, BEL-terminated)."""
    sys.stdout.write(f"\x1b]2;{s}\x07")
    sys.stdout.flush()


def osc52_copy(text):
    """Copy `text` to the system clipboard via OSC 52 (BEL-terminated).

    Works over SSH and inside tmux (with `set-clipboard on`); terminals
    that don't support OSC 52 simply ignore the sequence.
    """
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    sys.stdout.write(f"\x1b]52;c;{payload}\x07")
    sys.stdout.flush()


# DECSCUSR shape codes (steady variants; blink is one less).
_CURSOR_SHAPES = {"block": 2, "underline": 4, "bar": 6}


def set_cursor_shape(shape, blink=False):
    """Set the cursor shape via DECSCUSR: 'block', 'underline', or 'bar'."""
    n = _CURSOR_SHAPES.get(shape)
    if n is None:
        raise ValueError(f"bad cursor shape: {shape!r}")
    if blink:
        n -= 1
    sys.stdout.write(f"{CSI}{n} q")
    sys.stdout.flush()


# ----------------------------------------------------------------------------
# Width-aware helpers (so wide glyphs / colored strings line up)
# ----------------------------------------------------------------------------

import unicodedata
import re

_SGR_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(s):
    return _SGR_RE.sub("", s)


@functools.lru_cache(maxsize=1024)
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
    s = strip_ansi(s)
    if s.isascii():
        # Fast path: every wide (East Asian W/F, emoji) and combining
        # character is non-ASCII, so ASCII width == length.
        return len(s)
    return sum(char_width(c) for c in s)


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
    With focus=True, enables focus in/out reporting (mode 1004) so
    read_key yields FocusEvent when the terminal window gains/loses focus.
    With title=..., pushes the current window title, sets the given one,
    and pops the original back on exit.
    Bracketed paste (mode 2004) is always enabled so a paste arrives as a
    single PasteEvent instead of a flood of keystrokes; terminals that
    don't support it are unaffected.
    Restores the terminal on exit even if an exception propagates.
    """

    def __init__(self, mouse=False, focus=False, title=None):
        self.fd = sys.stdin.fileno()
        self.old = None
        self.mouse = mouse
        self.focus = focus
        self.title = title
        self._cursor_set = False
        self._resized = False

    def __enter__(self):
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        enter_alt_screen()
        sys.stdout.write(f"{CSI}?2004h")      # bracketed paste (protective)
        if self.focus:
            sys.stdout.write(f"{CSI}?1004h")  # focus in/out reporting
        if self.title is not None:
            sys.stdout.write(f"{CSI}22;2t")   # push the current title
            set_title(self.title)
        sys.stdout.flush()
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
            if self._cursor_set:
                sys.stdout.write(f"{CSI}0 q")    # default cursor shape
            if self.title is not None:
                sys.stdout.write(f"{CSI}23;2t")  # pop the saved title
            if self.focus:
                sys.stdout.write(f"{CSI}?1004l")
            sys.stdout.write(f"{CSI}?2004l")
            self.set_mouse(False)
            exit_alt_screen()
        finally:
            if self.old is not None:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        return False

    def set_cursor_shape(self, shape, blink=False):
        """Like term.set_cursor_shape, but remembered so __exit__ resets
        the cursor to the terminal default."""
        set_cursor_shape(shape, blink)
        self._cursor_set = True

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


class PasteEvent:
    """A bracketed paste (mode 2004): the pasted text as one event."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return f"PasteEvent(text={self.text!r})"


class FocusEvent:
    """A terminal focus change (mode 1004). gained=True on focus-in."""

    __slots__ = ("gained",)

    def __init__(self, gained):
        self.gained = gained

    def __repr__(self):
        return f"FocusEvent(gained={self.gained})"


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


# Bracketed paste: body size cap and inner per-byte deadline.  Paste bytes
# arrive in bulk, so the 0.02s between-bytes Esc heuristic must not apply;
# a pause this long really means the end marker was lost.
_PASTE_LIMIT = 1024 * 1024  # 1 MiB of body; the rest is drained and dropped
_PASTE_TIMEOUT = 0.5
_PASTE_END = b"\x1b[201~"


class _KeyDecoder:
    """Escape/UTF-8 key decoding driven by a `read(n, timeout)` callable.

    The callable blocks up to `timeout` seconds for input and returns at
    most `n` bytes (b"" on timeout).  Separating the decoding logic from
    the fd plumbing lets tests feed byte streams through an os.pipe.
    """

    def __init__(self, read):
        self._read = read

    def _read_paste(self):
        """Consume a bracketed-paste body up to ESC[201~ -> PasteEvent.

        Reads byte-at-a-time so nothing past the end marker is consumed
        (keystrokes may be queued right behind the paste).  Embedded ESC
        sequences are literal text, never decoded as keys.  The body is
        capped at _PASTE_LIMIT bytes; the overflow (and the end marker)
        is drained so it can't leak back in as keystrokes.
        """
        buf = bytearray()
        end = _PASTE_END
        while True:
            c = self._read(1, _PASTE_TIMEOUT)
            if not c:
                break  # end marker lost; salvage what arrived
            buf += c
            if buf.endswith(end):
                del buf[-len(end):]
                break
            if len(buf) >= _PASTE_LIMIT + len(end):
                # Cap hit: keep the first _PASTE_LIMIT bytes, then drain
                # the rest of the paste with a rolling end-marker window.
                tail = bytes(buf[-len(end):])
                del buf[_PASTE_LIMIT:]
                while tail != end:
                    c = self._read(1, _PASTE_TIMEOUT)
                    if not c:
                        break
                    tail = (tail + c)[-len(end):]
                break
        return PasteEvent(bytes(buf).decode("utf-8", "replace"))

    def read_key(self, timeout):
        ch = self._read(1, timeout)
        if not ch:
            return None
        b = ch[0]

        if b == 0x1b:  # ESC - could start a sequence
            # Peek for more bytes (very short window).
            seq = self._read(1, 0.02)
            if seq not in (b"[", b"O"):
                return Key.ESC
            # Read the rest of the sequence.
            body = b""
            while True:
                c = self._read(1, 0.02)
                if not c:
                    break
                body += c
                if c.isalpha() or c == b"~":
                    break
            if seq == b"[" and body == b"200~":
                return self._read_paste()  # bracketed paste start marker
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
                c = self._read(1, 0.01)
                if not c:
                    break
                buf += c
            try:
                return buf.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return chr(b)


def _fd_reader(fd):
    """Wrap `fd` as the `read(n, timeout)` callable _KeyDecoder expects."""
    def read(n, timeout):
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            return b""
        return os.read(fd, n)
    return read


def read_key(timeout=0.2, fd=None):
    """Block up to `timeout` seconds for a keypress.

    Returns a Key.* constant, a single character, or None on timeout.
    Decodes the common CSI/SS3 escape sequences for arrows, etc.
    `fd` defaults to sys.stdin.
    """
    if fd is None:
        fd = sys.stdin.fileno()
    return _KeyDecoder(_fd_reader(fd)).read_key(timeout)


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
    if intro == b"[" and text in ("I", "O"):  # focus in/out (mode 1004)
        return FocusEvent(text == "I")
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
        self._prev = []      # previous frame, padded to width (emit cache)
        self._prev_raw = []  # previous frame, raw pre-pad lines (memo keys)
        self._size = (0, 0)
        self._sync = sync

    def reset(self):
        """Force a full repaint on the next render (e.g. after resize)."""
        self._prev = []
        self._prev_raw = []
        sys.stdout.write(f"{CSI}2J")

    def render(self, lines, size):
        cols, rows = size
        if size != self._size:
            self.reset()
            self._size = size
        # Raw-line memo: padding every line dominates the frame cost, so
        # lines whose raw text is unchanged skip pad+compare+emit entirely
        # (same raw at the same width pads to the same string). Only
        # changed lines are padded and diffed against the previous padded
        # frame, and their padded form is cached so the NEXT frame's
        # comparison stays valid. First frames (and post-reset frames)
        # have no memo, so they emit exactly what they always did.
        prev, prev_raw = self._prev, self._prev_raw
        frame = []
        frame_raw = []
        out = []
        for i in range(rows):
            raw = lines[i] if i < len(lines) else ""
            if i < len(prev_raw) and prev_raw[i] == raw:
                frame.append(prev[i])
                frame_raw.append(raw)
                continue
            line = pad(raw, cols)
            if i >= len(prev) or prev[i] != line:
                out.append(move(i + 1, 1))
                out.append(line)
                out.append(clear_to_eol())
            frame.append(line)
            frame_raw.append(raw)
        if out:
            payload = "".join(out)
            if self._sync:
                payload = f"{CSI}?2026h{payload}{CSI}?2026l"
            sys.stdout.write(payload)
            sys.stdout.flush()
        self._prev = frame
        self._prev_raw = frame_raw
