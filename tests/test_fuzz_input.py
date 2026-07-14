"""Deterministic fuzz tests for the escape-sequence key decoder.

Adversarial byte streams are fed through ``puretui.term.read_key`` via an
``os.pipe`` whose write end is dribbled from a background thread in
variable-size chunks with tiny sleeps, so the decoder's short inter-byte
timeouts are exercised for real, not just the happy buffered path.

Everything is seeded and reproducible: three fixed seeds always run, plus
one extra run whose seed can be overridden with TUI_FUZZ_SEED=<int>.  Every
failure message carries the seed so a CI hit can be replayed locally.

Contract under test (see tui/term.py):
  * read_key never raises, with one documented exception: a 0x03 byte at
    the top-level dispatch raises KeyboardInterrupt.  The strict tests
    strip 0x03 from the corpus and allow no exception at all; the Ctrl-C
    tests leave it in and allow only KeyboardInterrupt.
  * every return value is None, a str (plain characters and the Key.*
    constants are strings), or a MouseEvent/PasteEvent/FocusEvent.
  * an unterminated bracketed paste (ESC[200~ with no ESC[201~) must not
    hang: the per-byte deadline / EOF path has to bail out.
"""

import os
import random
import threading
import time
import unittest

from puretui.term import FocusEvent, Key, MouseEvent, PasteEvent, read_key

FIXED_SEEDS = (1337, 20260714, 8675309)
ENV_SEED_DEFAULT = 0xF00D
DEADLINE = 2.0  # hard wall-clock budget per seed, seconds

# Well-formed sequences the decoder should recognise; the corpus includes
# every prefix of each of these (truncated-at-every-length coverage) as
# well as the full form embedded mid-garbage.
_VALID = (
    b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D",
    b"\x1b[H", b"\x1b[F", b"\x1b[Z",
    b"\x1bOA", b"\x1bOB", b"\x1bOC", b"\x1bOD",
    b"\x1b[1~", b"\x1b[3~", b"\x1b[4~", b"\x1b[5~", b"\x1b[6~",
    b"\x1b[1;5A", b"\x1b[1;2C",
    b"\x1b[<0;10;5M", b"\x1b[<0;10;5m", b"\x1b[<64;1;1M", b"\x1b[<32;3;9M",
    b"\x1b[I", b"\x1b[O",
    b"\x1b[200~", b"\x1b[201~",
)

# Huge / malformed parameter blocks, including hostile mouse reports.
_GARBAGE_PARAMS = (
    b"\x1b[99999999;-1;;;m",
    b"\x1b[<8191;99999;0M",
    b"\x1b[;;;~",
    b"\x1b[<;;M",
    b"\x1b[<-1;-2;-3m",
    b"\x1b[<0;0;0m",
    b"\x1b[" + b"9" * 200 + b"~",
    b"\x1b[<" + b"1" * 64 + b";2;3M",
    b"\x1b[<1;2M",  # too few fields
    b"\x1b[<1;2;3;4;5M",  # too many fields
)

# Invalid UTF-8: lone continuations, overlong encodings, truncated
# multibyte heads, and bytes (0xF5-0xFF) that never appear in UTF-8.
_BAD_UTF8 = (
    b"\x80", b"\xbf", b"\x80\x80\x80",
    b"\xc0\xaf",           # overlong "/"
    b"\xe0\x80\xaf",       # overlong, 3-byte form
    b"\xf0\x80\x80\xaf",   # overlong, 4-byte form
    b"\xc2",               # truncated 2-byte head
    b"\xe2\x82",           # truncated 3-byte head
    b"\xf0\x9f\x92",       # truncated 4-byte head
    b"\xf5\x80\x80\x80", b"\xf8", b"\xfe", b"\xff",
)


def _rand_bytes(rng, lo, hi):
    return bytes(rng.randrange(256) for _ in range(rng.randint(lo, hi)))


def _build_corpus(seed):
    """Deterministic adversarial byte stream for one fuzz run.

    May contain 0x03; callers strip it (strict variant) or accept the
    contractual KeyboardInterrupt (Ctrl-C variant).
    """
    rng = random.Random(seed)
    segs = []
    # 1. Pure random bytes.
    for _ in range(30):
        segs.append(_rand_bytes(rng, 1, 24))
    # 2. Every valid sequence truncated at every length.
    for seq in _VALID:
        for i in range(1, len(seq) + 1):
            segs.append(seq[:i])
    # 3. Huge / garbage parameters and mouse garbage.
    segs.extend(_GARBAGE_PARAMS)
    # 4. Invalid UTF-8, fixed and random high-byte runs.
    segs.extend(_BAD_UTF8)
    for _ in range(10):
        segs.append(bytes(rng.randrange(0x80, 0x100)
                          for _ in range(rng.randint(1, 6))))
    # 5. Valid sequences embedded mid-garbage.
    for _ in range(15):
        segs.append(_rand_bytes(rng, 0, 8) + rng.choice(_VALID) +
                    _rand_bytes(rng, 0, 8))
    # 6. Terminated pastes with hostile bodies (embedded ESC, high bytes).
    for _ in range(4):
        body = _rand_bytes(rng, 0, 64).replace(b"\x1b[201~", b"")
        segs.append(b"\x1b[200~" + body + b"\x1b[201~")
    # Loose end markers so paste starts shuffled in from (2)/(5) can
    # terminate mid-stream instead of swallowing the whole tail.
    segs.extend([b"\x1b[201~"] * 6)
    rng.shuffle(segs)
    # 7. Unterminated paste at the very end: the terminator never arrives,
    #    so the paste path must bail out via its deadline / EOF, not hang.
    segs.append(b"\x1b[200~" + b"the end marker never arrives")
    return b"".join(segs)


def _run_fuzz(seed, corpus, allow_interrupt):
    """Dribble `corpus` through a pipe and pump read_key until drained.

    Returns (events, interrupts).  Raises AssertionError (with the seed in
    the message) on any contract violation or deadline overrun.
    """
    hint = "seed=%d; rerun with TUI_FUZZ_SEED=%d" % (seed, seed)
    rng = random.Random(seed ^ 0x5EED)  # chunking independent of corpus
    r, w = os.pipe()
    done = threading.Event()

    def feed():
        try:
            i = 0
            while i < len(corpus):
                n = rng.randint(1, 64)
                os.write(w, corpus[i:i + n])
                i += n
                time.sleep(rng.random() * 0.002)
        finally:
            done.set()
            os.close(w)  # EOF lets the reader drain instantly

    t = threading.Thread(target=feed)
    t.daemon = True
    start = time.perf_counter()
    t.start()
    events = []
    interrupts = 0
    idle = 0
    try:
        while True:
            if time.perf_counter() - start > DEADLINE:
                raise AssertionError(
                    "fuzz run overran the %.1fs deadline (%s)"
                    % (DEADLINE, hint))
            try:
                ev = read_key(timeout=0.01, fd=r)
            except KeyboardInterrupt:
                if not allow_interrupt:
                    raise AssertionError(
                        "KeyboardInterrupt escaped although 0x03 was "
                        "stripped from the corpus (%s)" % hint)
                interrupts += 1
                continue
            except Exception as exc:
                raise AssertionError(
                    "decoder raised %r (%s)" % (exc, hint))
            if ev is None:
                if done.is_set():
                    idle += 1
                    if idle >= 8:  # pipe is at EOF and fully drained
                        break
                continue
            idle = 0
            if not isinstance(ev, (str, MouseEvent, PasteEvent, FocusEvent)):
                raise AssertionError(
                    "decoder returned unexpected value %r (%s)" % (ev, hint))
            events.append(ev)
    finally:
        t.join(DEADLINE)
        os.close(r)
    if t.is_alive():
        raise AssertionError("writer thread wedged; pipe not drained (%s)"
                             % hint)
    return events, interrupts


class TestFuzzStrict(unittest.TestCase):
    """0x03 stripped from the corpus: no exception of any kind may escape."""

    def _run(self, seed):
        corpus = _build_corpus(seed).replace(b"\x03", b"")
        events, interrupts = _run_fuzz(seed, corpus, allow_interrupt=False)
        self.assertEqual(interrupts, 0)
        # Sanity: the run actually decoded things, including at least one
        # recognised key and one paste (both are guaranteed by the corpus).
        self.assertTrue(events, "no events decoded (seed=%d)" % seed)
        self.assertTrue(any(ev == Key.UP for ev in events),
                        "no Key.UP decoded (seed=%d)" % seed)
        self.assertTrue(any(isinstance(ev, PasteEvent) for ev in events),
                        "no PasteEvent decoded (seed=%d)" % seed)

    def test_seed_1337(self):
        self._run(FIXED_SEEDS[0])

    def test_seed_20260714(self):
        self._run(FIXED_SEEDS[1])

    def test_seed_8675309(self):
        self._run(FIXED_SEEDS[2])

    def test_seed_from_env(self):
        # Override with e.g. TUI_FUZZ_SEED=12345 to replay a CI failure or
        # widen local coverage; the seed is embedded in every failure.
        seed = int(os.environ.get("TUI_FUZZ_SEED", ENV_SEED_DEFAULT))
        self._run(seed)


class TestFuzzCtrlC(unittest.TestCase):
    """0x03 left in: KeyboardInterrupt is the single allowed exception."""

    def _run(self, seed):
        # A leading 0x03 guarantees at least one top-level-dispatch Ctrl-C;
        # the rest of the corpus keeps whatever 0x03 bytes it generated.
        corpus = b"\x03" + _build_corpus(seed)
        events, interrupts = _run_fuzz(seed, corpus, allow_interrupt=True)
        self.assertGreaterEqual(interrupts, 1,
                                "contractual KeyboardInterrupt never raised "
                                "(seed=%d)" % seed)
        self.assertTrue(events, "no events decoded (seed=%d)" % seed)

    def test_seed_1337(self):
        self._run(FIXED_SEEDS[0])

    def test_seed_20260714(self):
        self._run(FIXED_SEEDS[1])

    def test_seed_8675309(self):
        self._run(FIXED_SEEDS[2])

    def test_seed_from_env(self):
        seed = int(os.environ.get("TUI_FUZZ_SEED", ENV_SEED_DEFAULT))
        self._run(seed)


class TestDecoderContracts(unittest.TestCase):
    """Deterministic pinned cases for the sharpest decoder edges."""

    def _feed(self, data):
        r, w = os.pipe()
        os.write(w, data)
        os.close(w)
        return r

    def test_unterminated_paste_does_not_hang(self):
        r = self._feed(b"\x1b[200~hello")
        start = time.perf_counter()
        try:
            ev = read_key(timeout=0.1, fd=r)
        finally:
            os.close(r)
        self.assertIsInstance(ev, PasteEvent)
        self.assertEqual(ev.text, "hello")
        self.assertLess(time.perf_counter() - start, DEADLINE)

    def test_ctrl_c_raises_by_contract(self):
        r = self._feed(b"\x03")
        try:
            self.assertRaises(KeyboardInterrupt, read_key, 0.1, r)
        finally:
            os.close(r)

    def test_hostile_sequences_do_not_raise(self):
        blobs = list(_GARBAGE_PARAMS) + list(_BAD_UTF8) + [
            b"\x1b", b"\x1b\x1b\x1b", b"\x1b[", b"\x1bO",
        ]
        for blob in blobs:
            r = self._feed(blob)
            try:
                while True:
                    ev = read_key(timeout=0.05, fd=r)
                    if ev is None:
                        break
                    self.assertIsInstance(
                        ev, (str, MouseEvent, PasteEvent, FocusEvent),
                        "unexpected value %r for input %r" % (ev, blob))
            finally:
                os.close(r)


if __name__ == "__main__":
    unittest.main()
