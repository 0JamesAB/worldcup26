"""Frame-loop scaffold: run() behavior, signature, and timeout helper."""

import inspect
import unittest
from unittest import mock

import tui.app
from tui.app import _timeout, run


class FakeRawTerminal:
    """Stands in for term.RawTerminal: records the mouse flag and serves
    a scripted queue of take_resize() results."""

    last = None

    def __init__(self, mouse=False):
        self.mouse = mouse
        self.resizes = []
        self.entered = self.exited = False
        FakeRawTerminal.last = self

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True
        return False

    def take_resize(self):
        return self.resizes.pop(0) if self.resizes else False


class FakeRenderer:
    """Stands in for term.Renderer: counts reset() and records frames."""

    last = None

    def __init__(self, sync=True):
        self.resets = 0
        self.frames = []
        FakeRenderer.last = self

    def reset(self):
        self.resets += 1

    def render(self, lines, size):
        self.frames.append((list(lines), size))


class RunCase(unittest.TestCase):
    """Drives run() with stubbed terminal plumbing.

    `keys` is the scripted sequence returned by read_key; when it runs
    out, KeyboardInterrupt is raised (which run() must swallow).
    """

    COLS, ROWS = 20, 5

    def drive(self, keys, **kwargs):
        keys = list(keys)

        def fake_read_key(timeout=0.2):
            if not keys:
                raise KeyboardInterrupt
            return keys.pop(0)

        with mock.patch.multiple(
                tui.app,
                RawTerminal=FakeRawTerminal,
                Renderer=FakeRenderer,
                read_key=fake_read_key,
                terminal_size=lambda: (self.COLS, self.ROWS)):
            run(kwargs.pop("render", lambda cols, rows, frame: ["frame"]),
                **kwargs)
        return FakeRawTerminal.last, FakeRenderer.last

    def test_exits_when_on_key_returns_false(self):
        seen = []

        def on_key(key):
            seen.append(key)
            return key != "q"

        _, renderer = self.drive(["a", "q", "x"], on_key=on_key)
        self.assertEqual(seen, ["a", "q"])  # "x" never consumed
        self.assertEqual(len(renderer.frames), 2)

    def test_falsy_non_false_does_not_exit(self):
        seen = []

        def on_key(key):
            seen.append(key)
            return 0 if key == "a" else None  # falsy but not False

        _, renderer = self.drive(["a", "b"], on_key=on_key)
        # Loop survived both keys and ended via KeyboardInterrupt,
        # which run() swallows (this call returning at all proves it).
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(len(renderer.frames), 3)

    def test_none_key_skips_on_key(self):
        seen = []
        self.drive([None, None], on_key=lambda k: seen.append(k))
        self.assertEqual(seen, [])

    def test_render_gets_size_and_incrementing_frame(self):
        calls = []

        def render(cols, rows, frame):
            calls.append((cols, rows, frame))
            return ["hi"]

        _, renderer = self.drive([None, "q"], render=render,
                                 on_key=lambda k: False)
        self.assertEqual(calls, [(self.COLS, self.ROWS, 0),
                                 (self.COLS, self.ROWS, 1)])
        self.assertEqual(renderer.frames,
                         [(["hi"], (self.COLS, self.ROWS))] * 2)

    def test_on_tick_runs_every_iteration(self):
        ticks = []
        self.drive([None, None, "q"], on_key=lambda k: k != "q",
                   on_tick=ticks.append)
        # One tick per completed iteration; the breaking iteration exits
        # before its tick.
        self.assertEqual(ticks, [1, 2])

    def test_resize_triggers_renderer_reset(self):
        def drive_with_resizes(resizes):
            keys = ["q"] * (len(resizes) + 1)

            def fake_read_key(timeout=0.2):
                return keys.pop(0)

            def make_tw(mouse=False):
                tw = FakeRawTerminal(mouse=mouse)
                tw.resizes = list(resizes)
                return tw

            with mock.patch.multiple(
                    tui.app,
                    RawTerminal=make_tw,
                    Renderer=FakeRenderer,
                    read_key=fake_read_key,
                    terminal_size=lambda: (self.COLS, self.ROWS)):
                run(lambda cols, rows, frame: [], on_key=lambda k: False)
            return FakeRenderer.last

        self.assertEqual(drive_with_resizes([]).resets, 0)
        self.assertEqual(drive_with_resizes([True]).resets, 1)

    def test_keyboard_interrupt_swallowed_and_terminal_restored(self):
        tw, _ = self.drive([])  # first read_key raises KeyboardInterrupt
        self.assertTrue(tw.entered)
        self.assertTrue(tw.exited)

    def test_mouse_flag_reaches_raw_terminal(self):
        tw, _ = self.drive([], mouse=True)
        self.assertTrue(tw.mouse)
        tw, _ = self.drive([])
        self.assertFalse(tw.mouse)


class TestRunSignature(unittest.TestCase):
    def test_importable(self):
        self.assertTrue(hasattr(tui.app, "run"))
        self.assertTrue(callable(run))

    def test_params_and_defaults(self):
        sig = inspect.signature(run)
        params = sig.parameters
        self.assertEqual(
            list(params), ["render", "on_key", "fps", "mouse", "on_tick"])
        self.assertIs(params["render"].default, inspect.Parameter.empty)
        self.assertIsNone(params["on_key"].default)
        self.assertEqual(params["fps"].default, 8)
        self.assertIs(params["mouse"].default, False)
        self.assertIsNone(params["on_tick"].default)


class TestTimeout(unittest.TestCase):
    def test_default_fps(self):
        self.assertEqual(_timeout(8), 0.125)

    def test_clamps_zero(self):
        self.assertEqual(_timeout(0), 1.0)

    def test_clamps_negative(self):
        self.assertEqual(_timeout(-5), 1.0)

    def test_one_fps(self):
        self.assertEqual(_timeout(1), 1.0)


if __name__ == "__main__":
    unittest.main()
