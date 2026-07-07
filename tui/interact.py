"""
interact.py - Selection and scroll state helpers.

`ListState` tracks a cursor inside a list of `count` items and computes
the visible window that keeps the selection in view with minimal
scrolling. `ScrollState` tracks a scroll offset for content taller than
its viewport. Both clamp everything, so callers can feed key deltas in
without bounds checks.
"""


class ListState:
    """Cursor + scroll window over a list of `count` items."""

    def __init__(self, count=0, sel=0):
        self.count = max(0, count)
        self.sel = self._clamp(sel)
        self.offset = 0

    def _clamp(self, sel):
        if self.count <= 0:
            return 0
        return max(0, min(sel, self.count - 1))

    def set_count(self, n):
        """Update the item count, re-clamping the selection."""
        self.count = max(0, n)
        self.sel = self._clamp(self.sel)

    def move(self, delta):
        """Move the selection by `delta` items, clamped."""
        self.sel = self._clamp(self.sel + delta)

    def page(self, delta, visible):
        """Move the selection by `delta` pages of `visible` rows."""
        self.move(delta * max(0, visible))

    def home(self):
        self.sel = 0

    def end(self):
        self.sel = self._clamp(self.count - 1)

    def window(self, visible):
        """Return (start, stop) of the visible slice keeping sel in view.

        The window only scrolls when the selection leaves it, so it stays
        stable while the cursor moves inside the view.
        """
        if visible <= 0 or self.count <= 0:
            return (0, 0)
        # Clamp the remembered offset to the current extent.
        self.offset = max(0, min(self.offset, max(0, self.count - visible)))
        if self.sel < self.offset:
            self.offset = self.sel
        elif self.sel >= self.offset + visible:
            self.offset = self.sel - visible + 1
        return (self.offset, min(self.count, self.offset + visible))


class ScrollState:
    """Clamped scroll offset for `content` rows in a `viewport`."""

    def __init__(self, content=0, viewport=0, offset=0):
        self.content = max(0, content)
        self.viewport = max(0, viewport)
        self.offset = max(0, min(offset, self.max_offset))

    @property
    def max_offset(self):
        return max(0, self.content - self.viewport)

    def set_extent(self, content, viewport):
        """Update content/viewport sizes, re-clamping the offset."""
        self.content = max(0, content)
        self.viewport = max(0, viewport)
        self.offset = max(0, min(self.offset, self.max_offset))

    def scroll(self, delta):
        """Scroll by `delta` rows, clamped."""
        self.offset = max(0, min(self.offset + delta, self.max_offset))

    def page(self, delta):
        """Scroll by `delta` viewports, clamped."""
        self.scroll(delta * self.viewport)

    def home(self):
        self.offset = 0

    def end(self):
        self.offset = self.max_offset

    @property
    def pct(self):
        """Scroll position as an int percentage (0 when it all fits)."""
        m = self.max_offset
        if m <= 0:
            return 0
        return int(round(self.offset * 100 / m))

    @property
    def at_top(self):
        return self.offset <= 0

    @property
    def at_bottom(self):
        return self.offset >= self.max_offset


class HitMap:
    """Frame-scoped registry of clickable screen regions.

    Views call add() for each interactive region while rendering a frame;
    the input loop calls lookup() with a MouseEvent's row/col to find the
    action under the pointer. Regions added later win overlaps (draw
    order = z-order). Rebuild (clear + add) every frame so regions always
    match what is on screen.
    """

    def __init__(self):
        self._regions = []

    def clear(self):
        self._regions = []

    def add(self, r, c, h, w, action):
        """Register rows [r, r+h) x cols [c, c+w) as `action` (any value)."""
        if h > 0 and w > 0:
            self._regions.append((r, c, h, w, action))

    def lookup(self, row, col):
        """The action under (row, col), or None. Last-added wins."""
        for r, c, h, w, action in reversed(self._regions):
            if r <= row < r + h and c <= col < c + w:
                return action
        return None

    def __len__(self):
        return len(self._regions)


class LineEdit:
    """Single-line text editor state. Pure state: no drawing here.

    Feed keys from `term.read_key` into handle_key(); printable
    characters insert at the cursor, and BACKSPACE/DELETE/LEFT/RIGHT/
    HOME/END edit or move (the Key.* constants are plain strings, so
    this module stays term-free). handle_key returns True when it
    consumed the key and False otherwise, so callers can layer their
    own bindings on top (ENTER, ESC, TAB, mouse events fall through).
    """

    def __init__(self, text=""):
        self.buf = text
        self.cursor = len(text)

    @property
    def text(self):
        return self.buf

    def clear(self):
        self.buf = ""
        self.cursor = 0

    def handle_key(self, key):
        """Apply `key`; True if consumed, False for the caller."""
        if not isinstance(key, str):
            return False
        if key == "LEFT":
            self.cursor = max(0, self.cursor - 1)
        elif key == "RIGHT":
            self.cursor = min(len(self.buf), self.cursor + 1)
        elif key == "HOME":
            self.cursor = 0
        elif key == "END":
            self.cursor = len(self.buf)
        elif key == "BACKSPACE":
            if self.cursor > 0:
                self.buf = self.buf[:self.cursor - 1] + self.buf[self.cursor:]
                self.cursor -= 1
        elif key == "DELETE":
            self.buf = self.buf[:self.cursor] + self.buf[self.cursor + 1:]
        elif len(key) == 1 and key.isprintable():
            self.buf = self.buf[:self.cursor] + key + self.buf[self.cursor:]
            self.cursor += 1
        else:
            return False
        return True
