"""Frame-loop scaffold and app kit: run(), App dispatch/stack, toasts."""

import inspect
import unittest
from unittest import mock

import tui.app
from tui.app import App, Toast, Toasts, _timeout, run
from tui.region import Region
from tui.term import Key, MouseEvent


class FakeRawTerminal:
    """Stands in for term.RawTerminal: records the mouse flag and serves
    a scripted queue of take_resize() results."""

    last = None

    def __init__(self, mouse=False):
        self.mouse = mouse
        self.mouse_calls = []
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

    def set_mouse(self, on):
        self.mouse = bool(on)
        self.mouse_calls.append(self.mouse)


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


def _noop_render(root, app):
    pass


def make_app(**kwargs):
    """An App with three stock views wired to recording keymaps."""
    app = App(**kwargs)
    app.calls = []
    app.add_view("live", _noop_render,
                 keys={"x": lambda: app.calls.append("live.x"),
                       ("a", "b"): lambda: app.calls.append("live.ab")})
    app.add_view("team", _noop_render)
    app.add_view("detail", _noop_render)
    app.bind({"x": lambda: app.calls.append("global.x"),
              "q": lambda: app.calls.append("global.q"),
              ("g", "G"): lambda: app.calls.append("global.gG")})
    return app


class AppStackCase(unittest.TestCase):
    def test_view_is_none_on_empty_stack(self):
        app = App()
        self.assertIsNone(app.view)

    def test_add_view_does_not_seed_stack(self):
        app = make_app()
        self.assertEqual(app.stack, [])
        self.assertIsNone(app.view)

    def test_goto_resets_stack(self):
        app = make_app()
        app.goto("live")
        app.push("detail")
        app.goto("team")
        self.assertEqual(app.stack, ["team"])
        self.assertEqual(app.view, "team")

    def test_push_and_pop(self):
        app = make_app()
        app.goto("live")
        app.push("team")
        app.push("detail")
        self.assertEqual(app.view, "detail")
        app.pop()
        self.assertEqual(app.view, "team")
        app.pop()
        self.assertEqual(app.view, "live")

    def test_pop_is_noop_at_depth_one(self):
        app = make_app()
        app.goto("live")
        app.pop()
        self.assertEqual(app.stack, ["live"])

    def test_navigation_marks_dirty(self):
        app = make_app()
        for do in (lambda: app.goto("live"),
                   lambda: app.push("detail"),
                   lambda: app.pop()):
            app.dirty = False
            do()
            self.assertTrue(app.dirty)

    def test_team_detail_esc_esc_unwind(self):
        """The authorized 0.5.0 behavior fix: TEAM -> DETAIL -> Esc lands
        back on TEAM, and a second Esc stays put at the stack root (the
        old prev_view scalar bounced to a stale view instead)."""
        app = make_app()
        app.goto("team")
        app.push("detail")
        self.assertTrue(app.dispatch_key(Key.ESC))
        self.assertEqual(app.view, "team")
        self.assertFalse(app.dispatch_key(Key.ESC))
        self.assertEqual(app.view, "team")


class DispatchKeyCase(unittest.TestCase):
    def test_view_keys_beat_global(self):
        app = make_app()
        app.goto("live")
        self.assertTrue(app.dispatch_key("x"))
        self.assertEqual(app.calls, ["live.x"])

    def test_global_used_when_view_lacks_key(self):
        app = make_app()
        app.goto("team")
        self.assertTrue(app.dispatch_key("x"))
        self.assertEqual(app.calls, ["global.x"])

    def test_global_used_on_empty_stack(self):
        app = make_app()
        self.assertTrue(app.dispatch_key("q"))
        self.assertEqual(app.calls, ["global.q"])

    def test_capture_beats_view_and_global(self):
        app = make_app()
        app.goto("live")
        seen = []
        app.capture = lambda key: (seen.append(key), True)[1]
        self.assertTrue(app.dispatch_key("x"))
        self.assertEqual(seen, ["x"])
        self.assertEqual(app.calls, [])

    def test_capture_falsy_falls_through(self):
        app = make_app()
        app.goto("live")
        app.capture = lambda key: False
        self.assertTrue(app.dispatch_key("x"))
        self.assertEqual(app.calls, ["live.x"])

    def test_capture_cleared_restores_routing(self):
        app = make_app()
        app.goto("live")
        app.capture = lambda key: True
        app.dispatch_key("x")
        app.capture = None
        app.dispatch_key("x")
        self.assertEqual(app.calls, ["live.x"])

    def test_view_on_key_truthy_consumes(self):
        app = make_app()
        app.add_view("edit", _noop_render,
                     on_key=lambda key: key == "x")
        app.goto("edit")
        self.assertTrue(app.dispatch_key("x"))
        self.assertEqual(app.calls, [])      # global "x" never ran

    def test_view_on_key_falsy_falls_to_global(self):
        app = make_app()
        app.add_view("edit", _noop_render, on_key=lambda key: None)
        app.goto("edit")
        self.assertTrue(app.dispatch_key("x"))
        self.assertEqual(app.calls, ["global.x"])

    def test_view_keys_beat_view_on_key(self):
        app = make_app()
        hits = []
        app.add_view("edit", _noop_render,
                     keys={"x": lambda: hits.append("keys")},
                     on_key=lambda key: hits.append("on_key") or True)
        app.goto("edit")
        app.dispatch_key("x")
        self.assertEqual(hits, ["keys"])

    def test_tuple_keys_expand(self):
        app = make_app()
        app.goto("live")
        app.dispatch_key("a")
        app.dispatch_key("b")
        app.dispatch_key("g")
        app.dispatch_key("G")
        self.assertEqual(app.calls,
                         ["live.ab", "live.ab", "global.gG", "global.gG"])

    def test_esc_pops_only_when_deep(self):
        app = make_app()
        app.goto("live")
        app.push("detail")
        self.assertTrue(app.dispatch_key(Key.ESC))
        self.assertEqual(app.stack, ["live"])
        self.assertFalse(app.dispatch_key(Key.ESC))
        self.assertEqual(app.stack, ["live"])

    def test_bound_esc_beats_builtin_pop(self):
        app = make_app()
        app.add_view("modal", _noop_render,
                     keys={Key.ESC: lambda: app.calls.append("modal.esc")})
        app.goto("live")
        app.push("modal")
        self.assertTrue(app.dispatch_key(Key.ESC))
        self.assertEqual(app.calls, ["modal.esc"])
        self.assertEqual(app.stack, ["live", "modal"])  # no built-in pop

    def test_unbound_key_not_consumed(self):
        app = make_app()
        app.goto("live")
        self.assertFalse(app.dispatch_key("z"))


class DispatchMouseCase(unittest.TestCase):
    def wheel(self, direction):
        return MouseEvent(3, 4, "wheel_" + direction, "wheel")

    def press(self, row, col, button="left", kind="press"):
        return MouseEvent(row, col, button, kind)

    def test_wheel_prefers_view_on_wheel(self):
        app = App()
        deltas = []
        app.add_view("v", _noop_render, on_wheel=deltas.append)
        app.goto("v")
        self.assertTrue(app.dispatch_mouse(self.wheel("down")))
        self.assertTrue(app.dispatch_mouse(self.wheel("up")))
        self.assertEqual(deltas, [1, -1])

    def test_wheel_synthesizes_arrow_keys(self):
        app = App()
        keys = []
        app.add_view("v", _noop_render,
                     keys={Key.UP: lambda: keys.append(Key.UP),
                           Key.DOWN: lambda: keys.append(Key.DOWN)})
        app.goto("v")
        self.assertTrue(app.dispatch_mouse(self.wheel("down")))
        self.assertTrue(app.dispatch_mouse(self.wheel("up")))
        self.assertEqual(keys, [Key.DOWN, Key.UP])

    def test_left_press_invokes_callable_action(self):
        app = App()
        hit = []
        app.hits.add(2, 5, 1, 10, lambda: hit.append("go"))
        self.assertTrue(app.dispatch_mouse(self.press(2, 9)))
        self.assertEqual(hit, ["go"])

    def test_legacy_tuple_action_ignored(self):
        app = App()
        app.hits.add(2, 5, 1, 10, ("view", "live"))
        self.assertFalse(app.dispatch_mouse(self.press(2, 9)))

    def test_press_outside_hits_not_consumed(self):
        app = App()
        self.assertFalse(app.dispatch_mouse(self.press(0, 0)))

    def test_capture_drops_presses(self):
        app = App()
        app.capture = lambda key: True
        hit = []
        app.hits.add(0, 0, 5, 5, lambda: hit.append("go"))
        self.assertFalse(app.dispatch_mouse(self.press(1, 1)))
        self.assertEqual(hit, [])

    def test_non_left_and_non_press_ignored(self):
        app = App()
        hit = []
        app.hits.add(0, 0, 5, 5, lambda: hit.append("go"))
        self.assertFalse(app.dispatch_mouse(self.press(1, 1, button="right")))
        self.assertFalse(app.dispatch_mouse(self.press(1, 1, kind="release")))
        self.assertEqual(hit, [])


class ToastsCase(unittest.TestCase):
    """Toast/Toasts under a controlled clock (tui.app.time is patched)."""

    def run_clocked(self, body):
        clock = {"t": 1000.0}
        with mock.patch.object(tui.app.time, "time", lambda: clock["t"]):
            body(clock)

    def test_toast_fields_and_age(self):
        def body(clock):
            t = Toast("hi", kind="goal", ttl=5.0)
            clock["t"] += 2.0
            self.assertEqual(t.text, "hi")
            self.assertEqual(t.kind, "goal")
            self.assertEqual(t.ttl, 5.0)
            self.assertEqual(t.age, 2.0)
            self.assertTrue(t.alive)
            clock["t"] += 3.0
            self.assertFalse(t.alive)   # age == ttl is dead
        self.run_clocked(body)

    def test_bounded_append_keeps_newest_six(self):
        def body(clock):
            ts = Toasts()
            for i in range(8):
                ts.add(f"t{i}")
            self.assertEqual(len(ts), 6)
            self.assertEqual([t.text for t in ts],
                             [f"t{i}" for i in range(2, 8)])
            self.assertEqual(ts.latest().text, "t7")
        self.run_clocked(body)

    def test_add_drops_already_dead(self):
        def body(clock):
            ts = Toasts()
            ts.add("old", ttl=1.0)
            clock["t"] += 2.0
            ts.add("new", ttl=8.0)
            self.assertEqual([t.text for t in ts], ["new"])
        self.run_clocked(body)

    def test_prune_reports_change(self):
        def body(clock):
            ts = Toasts()
            ts.add("a", ttl=1.0)
            ts.add("b", ttl=8.0)
            self.assertFalse(ts.prune())        # nothing expired yet
            clock["t"] += 2.0
            self.assertTrue(ts.prune())         # "a" expired
            self.assertEqual([t.text for t in ts], ["b"])
            self.assertFalse(ts.prune())
        self.run_clocked(body)

    def test_latest_none_when_empty(self):
        self.assertIsNone(Toasts().latest())

    def test_app_toast_appends_and_marks_dirty(self):
        app = App()
        app.dirty = False
        app.toast("hello", "info", 4)
        self.assertTrue(app.dirty)
        self.assertEqual(app.toasts.latest().text, "hello")

    def test_invalidate_and_quit(self):
        app = App()
        app.dirty = False
        app.invalidate()
        self.assertTrue(app.dirty)
        self.assertTrue(app.running)
        app.quit()
        self.assertFalse(app.running)


class AppRunCase(unittest.TestCase):
    """Drives App.run() with the stubbed terminal plumbing (no tty)."""

    COLS, ROWS = 30, 8

    def drive(self, app, keys, frame_fn=_noop_render):
        keys = list(keys)
        timeouts = []

        def fake_read_key(timeout=0.2):
            timeouts.append(timeout)
            if not keys:
                raise KeyboardInterrupt
            return keys.pop(0)

        with mock.patch.multiple(
                tui.app,
                RawTerminal=FakeRawTerminal,
                Renderer=FakeRenderer,
                read_key=fake_read_key,
                terminal_size=lambda: (self.COLS, self.ROWS)):
            app.run(frame_fn)
        return FakeRawTerminal.last, FakeRenderer.last, timeouts

    def test_signature(self):
        params = inspect.signature(App.run).parameters
        self.assertEqual(list(params), ["self", "frame_fn"])
        init = inspect.signature(App.__init__).parameters
        self.assertEqual(list(init), ["self", "state", "fps", "tick",
                                      "mouse", "lock", "theme_base_style"])
        self.assertIsNone(init["state"].default)
        self.assertEqual(init["fps"].default, 8)
        self.assertEqual(init["tick"].default, 0.33)
        self.assertIs(init["mouse"].default, False)
        self.assertIsNone(init["lock"].default)
        self.assertIsNone(init["theme_base_style"].default)

    def test_first_frame_renders_before_first_key_wait(self):
        app = App()
        frames_when_key_ran = []
        app.bind({"q": lambda: (
            frames_when_key_ran.append(len(FakeRenderer.last.frames)),
            app.quit())})
        _, renderer, _ = self.drive(app, ["q"])
        self.assertEqual(frames_when_key_ran, [1])

    def test_quit_stops_loop_and_restores_terminal(self):
        app = App()
        app.bind({"q": app.quit})
        tw, _, _ = self.drive(app, ["q", "never"])
        self.assertFalse(app.running)
        self.assertTrue(tw.entered)
        self.assertTrue(tw.exited)

    def test_keyboard_interrupt_swallowed_and_running_cleared(self):
        app = App()
        tw, _, _ = self.drive(app, [])
        self.assertFalse(app.running)
        self.assertTrue(tw.exited)

    def test_read_timeout_follows_fps(self):
        app = App(fps=4)
        app.bind({"q": app.quit})
        _, _, timeouts = self.drive(app, ["q"])
        self.assertEqual(timeouts, [0.25])

    def test_frame_fn_gets_root_region_and_app(self):
        app = App(theme_base_style="")
        seen = []

        def frame_fn(root, a):
            seen.append((root, a))
            root.put(0, 0, "hi")

        app.bind({"q": app.quit})
        _, renderer, _ = self.drive(app, ["q"], frame_fn=frame_fn)
        root, a = seen[0]
        self.assertIsInstance(root, Region)
        self.assertIs(a, app)
        self.assertIs(root.hits, app.hits)
        self.assertEqual((root.h, root.w), (self.ROWS, self.COLS))
        self.assertEqual(len(renderer.frames), 1)
        self.assertEqual(renderer.frames[0][1], (self.COLS, self.ROWS))
        self.assertEqual(app.frame, 1)

    def test_hits_cleared_each_frame_and_click_routed(self):
        app = App(mouse=True)
        opened = []

        def frame_fn(root, a):
            root.hit(lambda: opened.append(a.frame), r=0, c=0, h=1, w=5)

        app.bind({"q": app.quit})
        self.drive(app, [MouseEvent(0, 2, "left", "press"), "q"],
                   frame_fn=frame_fn)
        self.assertEqual(opened, [1])
        self.assertEqual(len(app.hits), 1)   # rebuilt, not accumulated

    def test_mouse_flag_and_runtime_sync(self):
        app = App(mouse=True)
        app.bind({"m": lambda: setattr(app, "mouse_enabled", False),
                  "q": app.quit})
        tw, _, _ = self.drive(app, ["m", "q"])
        self.assertEqual(tw.mouse_calls, [False])
        self.assertFalse(tw.mouse)

    def test_resize_resets_renderer_and_repaints(self):
        app = App()
        app.bind({"q": app.quit})

        def make_tw(mouse=False):
            tw = FakeRawTerminal(mouse=mouse)
            tw.resizes = [False, True]
            return tw

        keys = [None, "q"]

        def fake_read_key(timeout=0.2):
            return keys.pop(0)

        with mock.patch.multiple(
                tui.app,
                RawTerminal=make_tw,
                Renderer=FakeRenderer,
                read_key=fake_read_key,
                terminal_size=lambda: (self.COLS, self.ROWS)):
            app.run(_noop_render)
        self.assertEqual(FakeRenderer.last.resets, 1)
        self.assertEqual(len(FakeRenderer.last.frames), 2)


if __name__ == "__main__":
    unittest.main()
