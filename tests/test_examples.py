"""
test_examples.py - Golden-text snapshots + smoke tests for examples/.

Each example renders one deterministic --snapshot frame through a real
subprocess; the ANSI-stripped text is compared against
tests/goldens/example_<name>_<w>x<h>.txt.

    GENERATE_GOLDENS=1 python3 -m unittest tests.test_examples

writes the goldens instead of comparing. In-process tests drive
logtail's App wiring through dispatch_key (the public test seam), and a
pty smoke test launches logtail for real and quits it with 'q'.
"""

import importlib.util
import os
import subprocess
import sys
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from puretui.term import Key, strip_ansi

GOLDEN_DIR = os.path.join(REPO, "tests", "goldens")
GENERATE = os.environ.get("GENERATE_GOLDENS") == "1"


def example_path(name):
    return os.path.join(REPO, "examples", name + ".py")


def snapshot_bytes(name, spec, extra=None):
    """Run `examples/<name>.py --snapshot spec` and return raw stdout."""
    cmd = [sys.executable, example_path(name), "--snapshot", spec]
    cmd += list(extra or [])
    out = subprocess.run(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, cwd=REPO, timeout=30)
    if out.returncode != 0:
        raise AssertionError("%s --snapshot %s exited %d: %s"
                             % (name, spec, out.returncode,
                                out.stderr.decode("utf-8", "replace")))
    return out.stdout


def load_logtail():
    spec = importlib.util.spec_from_file_location(
        "logtail_example", example_path("logtail"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestExampleGoldens(unittest.TestCase):
    """ANSI-stripped snapshot frames match the checked-in golden text."""

    CASES = [
        ("logtail", "100x30", []),
        ("logtail", "80x24", []),
        ("dashboard", "100x30", []),
    ]

    def test_snapshots_match_goldens(self):
        for name, spec, extra in self.CASES:
            with self.subTest(example=name, size=spec):
                frame = strip_ansi(
                    snapshot_bytes(name, spec, extra).decode("utf-8"))
                path = os.path.join(GOLDEN_DIR,
                                    "example_%s_%s.txt" % (name, spec))
                if GENERATE:
                    os.makedirs(GOLDEN_DIR, exist_ok=True)
                    with open(path, "w") as f:
                        f.write(frame)
                    continue
                self.assertTrue(
                    os.path.exists(path),
                    "missing golden %s (capture with GENERATE_GOLDENS=1)"
                    % path)
                with open(path) as f:
                    want = f.read()
                self.assertEqual(want, frame,
                                 "%s @ %s differs from golden" % (name, spec))

    def test_logtail_snapshot_deterministic(self):
        """Two subprocess runs produce byte-identical full-ANSI frames."""
        a = snapshot_bytes("logtail", "100x30")
        b = snapshot_bytes("logtail", "100x30")
        self.assertEqual(a, b)

    def test_logtail_seed_changes_output(self):
        base = snapshot_bytes("logtail", "100x30")
        other = snapshot_bytes("logtail", "100x30", ["--seed", "7"])
        self.assertNotEqual(base, other)


class TestLogtailWiring(unittest.TestCase):
    """Drive the logtail App in-process through dispatch_key."""

    def setUp(self):
        self.lt = load_logtail()
        self.st = self.lt.LogState()
        self.st.records = [self.lt.make_record(self.st)
                           for _ in range(self.lt.PREFILL)]
        self.app = self.lt.build_app(self.st)

    def frame(self, cols=100, rows=30):
        return strip_ansi("\n".join(
            self.lt.render_frame(self.app, cols, rows)))

    def test_enter_pushes_entry_and_esc_pops(self):
        self.frame()                       # sync ListState with the records
        self.app.dispatch_key(Key.ENTER)
        self.assertEqual(self.app.view, "entry")
        self.assertIn("log entry", self.frame())
        self.app.dispatch_key(Key.ESC)     # kit built-in: no handler exists
        self.assertEqual(self.app.view, "tail")

    def test_move_disables_follow(self):
        self.assertTrue(self.st.follow)
        self.app.dispatch_key(Key.UP)
        self.assertFalse(self.st.follow)
        self.app.dispatch_key("f")
        self.assertTrue(self.st.follow)

    def test_filter_capture_applies_and_toasts(self):
        self.app.dispatch_key("/")
        self.assertIsNotNone(self.app.capture)
        for ch in "err":
            self.app.dispatch_key(ch)
        self.app.dispatch_key(Key.TAB)     # ghost completes the level name
        self.assertEqual(self.st.edit.text, "ERROR")
        self.app.dispatch_key(Key.ENTER)
        self.assertIsNone(self.app.capture)
        self.assertEqual(self.st.filter_text, "ERROR")
        recs = self.lt.filtered(self.st)
        self.assertTrue(recs)
        self.assertTrue(all(r[1] == "ERROR" for r in recs))
        self.assertEqual(self.app.toasts.latest().text,
                         "%d matches" % len(recs))

    def test_filter_esc_cancels(self):
        self.app.dispatch_key("/")
        for ch in "warn":
            self.app.dispatch_key(ch)
        self.app.dispatch_key(Key.ESC)
        self.assertIsNone(self.app.capture)
        self.assertEqual(self.st.filter_text, "")

    def test_palette_level_command(self):
        self.app.dispatch_key(":")
        self.assertIsNotNone(self.app.capture)
        for ch in "level WARN":
            self.app.dispatch_key(ch)
        self.assertIn(":level WARN", self.frame())
        self.app.dispatch_key(Key.ENTER)
        self.assertIsNone(self.app.capture)
        self.assertEqual(self.st.min_level, self.lt.LEVELS.index("WARN"))
        self.assertTrue(all(r[1] in ("WARN", "ERROR")
                            for r in self.lt.filtered(self.st)))

    def test_palette_clear_and_quit(self):
        for ch in ":clear":
            self.app.dispatch_key(ch)
        self.app.dispatch_key(Key.ENTER)
        self.assertEqual(self.st.records, [])
        for ch in ":quit":
            self.app.dispatch_key(ch)
        self.app.dispatch_key(Key.ENTER)
        self.assertFalse(self.app.running)


@unittest.skipUnless(hasattr(os, "openpty") and sys.platform != "win32",
                     "needs a POSIX pty")
class TestLogtailPty(unittest.TestCase):
    def test_pty_launch_and_quit(self):
        """Launch logtail on a real pty, press q, expect a clean exit 0."""
        import fcntl
        import struct
        import termios
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ,
                    struct.pack("HHHH", 30, 100, 0, 0))
        p = subprocess.Popen([sys.executable, example_path("logtail")],
                             stdin=slave, stdout=slave, stderr=slave,
                             cwd=REPO, close_fds=True)
        os.close(slave)

        def drain(deadline):
            """Read the master (so the child never blocks on a full pty)
            until `deadline`; returns everything read."""
            import select
            buf = b""
            while time.time() < deadline:
                r, _, _ = select.select([master], [], [], 0.1)
                if r:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:        # child side closed
                        break
                    if not chunk:
                        break
                    buf += chunk
                if p.poll() is not None and not r:
                    break
            return buf

        try:
            drain(time.time() + 2.0)       # let it draw a few frames
            os.write(master, b"q")
            deadline = time.time() + 10
            while p.poll() is None and time.time() < deadline:
                drain(time.time() + 0.2)
            self.assertEqual(p.poll(), 0)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
