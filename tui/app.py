"""
app.py - Frame-loop scaffold and app kit for full-screen TUIs.

`run()` wraps the RawTerminal / Renderer / read_key plumbing that every
consumer otherwise hand-rolls: enter the alt screen, render a frame, poll
for a key, repeat until the key handler says stop or the user hits Ctrl-C.

`App` builds on the same loop and adds the routing every real app grows:
named views with per-view keymaps, a view stack (goto/push/pop with a
built-in Esc-pops-back), global key bindings, mouse dispatch through a
HitMap of zero-arg action closures, a `capture` hook for modal input,
and kit-side toast state. The kit owns input routing and interaction
state; the app owns every pixel (App never draws — the frame function
passed to App.run does).
"""

import threading
import time

from .canvas import Canvas
from .interact import HitMap
from .term import (Key, MouseEvent, RawTerminal, Renderer, read_key,
                   terminal_size)
from . import widgets


def _timeout(fps):
    """Per-frame key-poll timeout in seconds for a target frame rate."""
    return 1.0 / max(1, fps)


def run(render, on_key=None, fps=8, mouse=False, on_tick=None):
    """Drive a full-screen TUI until on_key returns False or Ctrl-C.

    render(cols, rows, frame) -> list of ANSI lines for the frame.
    on_key(key) -> return False to exit; key is a Key constant, str, or
    MouseEvent. on_tick(frame) runs once per loop iteration.
    """
    with RawTerminal(mouse=mouse) as tw:
        renderer = Renderer()
        frame = 0
        try:
            while True:
                if tw.take_resize():
                    renderer.reset()
                cols, rows = terminal_size()
                lines = render(cols, rows, frame)
                renderer.render(lines, (cols, rows))
                frame += 1
                key = read_key(timeout=_timeout(fps))
                if key is not None and on_key is not None:
                    if on_key(key) is False:
                        break
                if on_tick is not None:
                    on_tick(frame)
        except KeyboardInterrupt:
            pass


# ----------------------------------------------------------------------------
# Toasts - transient notification state (rendering stays app-side)
# ----------------------------------------------------------------------------

class Toast:
    """One transient notification: text, a kind tag, and a lifetime."""

    def __init__(self, text, kind="info", ttl=8.0):
        self.text = text
        self.kind = kind          # info | goal | error (app-defined tags)
        self.born = time.time()
        self.ttl = ttl

    @property
    def alive(self):
        return (time.time() - self.born) < self.ttl

    @property
    def age(self):
        return time.time() - self.born


class Toasts:
    """A bounded, self-expiring list of Toast objects.

    add() appends and trims to the newest `limit` living toasts; prune()
    drops the dead ones and reports whether anything changed (so the
    frame loop knows to repaint). Iterating yields oldest-first.
    """

    def __init__(self, limit=6):
        self.limit = limit
        self._items = []

    def add(self, text, kind="info", ttl=8.0):
        self._items.append(Toast(text, kind, ttl))
        self._items = [t for t in self._items if t.alive][-self.limit:]

    def prune(self):
        """Drop expired toasts; True if the list changed."""
        before = len(self._items)
        self._items = [t for t in self._items if t.alive]
        return len(self._items) != before

    def latest(self):
        """The newest toast, or None."""
        return self._items[-1] if self._items else None

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)


# ----------------------------------------------------------------------------
# App - view routing, keymaps, capture, and the frame loop
# ----------------------------------------------------------------------------

def _expand_keys(keymap):
    """Flatten a keymap whose keys may be tuples of keys."""
    out = {}
    for k, fn in (keymap or {}).items():
        if isinstance(k, tuple):
            for kk in k:
                out[kk] = fn
        else:
            out[k] = fn
    return out


class _View:
    """A registered view: its renderer plus per-view input handlers."""

    __slots__ = ("render", "keys", "on_key", "on_wheel")

    def __init__(self, render, keys, on_key, on_wheel):
        self.render = render
        self.keys = keys
        self.on_key = on_key
        self.on_wheel = on_wheel


class App:
    """Input routing + interaction state for a full-screen TUI.

    Register views with add_view(), global bindings with bind(), navigate
    with goto()/push()/pop(), then App.run(frame_fn) drives the loop.
    Every frame, frame_fn(root, app) draws the whole screen onto a fresh
    root Region wired to app.hits — the kit never draws a pixel.

    Key dispatch order (dispatch_key): app.capture, the active view's
    keymap, the view's on_key, the global keymap, then the one built-in:
    Esc pops the view stack when it is deeper than one view.

    `capture` is the entire modal system: a nullable callable(key)->bool
    that sees every key first; a truthy return consumes the key. While a
    capture is active, mouse presses are dropped.

    Threading contract: the frame loop renders under `self.lock`;
    background threads mutate shared state under the same lock and then
    call invalidate(). `dirty` is written without the lock — that is safe
    because a bool store is atomic and the loop is the only writer that
    clears it (single-writer contract).
    """

    def __init__(self, state=None, fps=8, tick=0.33, mouse=False, lock=None,
                 theme_base_style=None):
        self.state = state
        self.fps = fps
        self.tick = tick               # seconds between forced repaints
        self.mouse_enabled = mouse     # loop syncs the terminal to this
        self.lock = lock if lock is not None else threading.RLock()
        self.theme_base_style = theme_base_style

        self.hits = HitMap()           # rebuilt every rendered frame
        self.toasts = Toasts()
        self.capture = None            # callable(key)->bool, or None
        self.views = {}                # name -> _View
        self.stack = []                # view names; top is active
        self.keys = {}                 # global keymap
        self.running = True
        self.dirty = True
        self.frame = 0

    # -- views & bindings --

    @property
    def view(self):
        """The active view name (top of the stack), or None."""
        return self.stack[-1] if self.stack else None

    def add_view(self, name, render, keys=None, on_key=None, on_wheel=None):
        """Register a view. Tuple keys in `keys` expand to one entry each.

        The stack is not touched: seed it with goto()."""
        self.views[name] = _View(render, _expand_keys(keys), on_key, on_wheel)

    def bind(self, keymap):
        """Merge global bindings; tuple keys expand to one entry each."""
        self.keys.update(_expand_keys(keymap))

    def goto(self, name):
        """Jump to `name`, resetting the stack to just that view."""
        self.stack = [name]
        self.dirty = True

    def push(self, name):
        """Open `name` on top of the current view (Esc returns)."""
        self.stack.append(name)
        self.dirty = True

    def pop(self):
        """Back to the view below; no-op at the root view."""
        if len(self.stack) > 1:
            self.stack.pop()
            self.dirty = True

    # -- dispatch (public: the test seam) --

    def dispatch_key(self, key):
        """Route a key press. Returns True if something consumed it."""
        if self.capture is not None and self.capture(key):
            return True
        view = self.views.get(self.view)
        if view is not None:
            fn = view.keys.get(key)
            if fn is not None:
                fn()
                return True
            if view.on_key is not None and view.on_key(key):
                return True
        fn = self.keys.get(key)
        if fn is not None:
            fn()
            return True
        if key == Key.ESC and len(self.stack) > 1:
            self.pop()
            return True
        return False

    def dispatch_mouse(self, ev):
        """Route a MouseEvent. Returns True if something consumed it.

        Wheel goes to the active view's on_wheel(delta) (+1 down, -1 up)
        or, absent that, is synthesized into Key.DOWN/Key.UP through
        dispatch_key. A left press looks up app.hits: a callable action
        is invoked; anything else is ignored (compatibility for raw
        HitMap users). While a capture is active, ALL mouse input is
        dropped — the modal owns the interaction.
        """
        if self.capture is not None:
            return False
        if ev.kind == "wheel":
            delta = 1 if ev.button == "wheel_down" else -1
            view = self.views.get(self.view)
            if view is not None and view.on_wheel is not None:
                view.on_wheel(delta)
                return True
            return self.dispatch_key(Key.DOWN if delta > 0 else Key.UP)
        if ev.kind != "press" or ev.button != "left":
            return False
        action = self.hits.lookup(ev.row, ev.col)
        if callable(action):
            action()
            return True
        return False

    # -- thread-safe signals --

    def toast(self, text, kind="info", ttl=8.0):
        """Post a notification (safe from background threads)."""
        with self.lock:
            self.toasts.add(text, kind, ttl)
        self.dirty = True

    def invalidate(self):
        """Request a repaint (safe from background threads)."""
        self.dirty = True

    def quit(self):
        """Stop the frame loop after the current iteration."""
        self.running = False

    # -- the loop --

    def run(self, frame_fn):
        """Drive the app until quit() or Ctrl-C.

        Per iteration: absorb resizes, sync the terminal's mouse mode to
        self.mouse_enabled, expire toasts, tick the animation clock, and
        repaint if dirty — the first frame renders before the first key
        wait — then poll for input and dispatch it. The frame canvas is
        allocated once per terminal size and clear()ed in place between
        frames rather than reallocated.
        """
        renderer = Renderer()
        timeout = _timeout(self.fps)
        last_tick = 0.0
        cv = None
        cv_size = None
        try:
            with RawTerminal(mouse=self.mouse_enabled) as tw:
                while self.running:
                    if tw.take_resize():
                        renderer.reset()
                        self.dirty = True
                    if tw.mouse != self.mouse_enabled:
                        tw.set_mouse(self.mouse_enabled)
                    with self.lock:   # add() from producer threads locks too
                        pruned = self.toasts.prune()
                    if pruned:
                        self.dirty = True
                    now = time.time()
                    if now - last_tick >= self.tick:
                        self.dirty = True
                        last_tick = now
                    if self.dirty:
                        cols, rows = terminal_size()
                        with self.lock:
                            self.frame += 1
                            self.hits.clear()
                            base = (self.theme_base_style or
                                    widgets.base_style())
                            if cv is None or cv_size != (cols, rows):
                                cv = Canvas(cols, rows, base)
                                cv_size = (cols, rows)
                            else:
                                cv.clear(base)
                            frame_fn(cv.region(hits=self.hits), self)
                            renderer.render(cv.to_lines(), (cols, rows))
                        self.dirty = False
                    key = read_key(timeout=timeout)
                    if key is not None:
                        if isinstance(key, MouseEvent):
                            if self.mouse_enabled:
                                self.dispatch_mouse(key)
                        else:
                            self.dispatch_key(key)
                        self.dirty = True
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
