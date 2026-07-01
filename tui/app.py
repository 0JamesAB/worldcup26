"""
app.py - Frame-loop scaffold for full-screen TUIs.

Wraps the RawTerminal / Renderer / read_key plumbing that every consumer
otherwise hand-rolls: enter the alt screen, render a frame, poll for a key,
repeat until the key handler says stop or the user hits Ctrl-C.
"""

from .term import RawTerminal, Renderer, read_key, terminal_size


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
