"""bench.py - Performance benchmarks for the tui library.

Measures the primitives that dominate a live TUI:

    canvas_alloc       constructing a Canvas grid
    full_frame         composing a dashboard-like frame (boxes, a table,
                       meters, a sparkline, tab bar and footer) and
                       pushing it through a fresh Renderer (full repaint)
    incremental_frame  re-rendering the same frame with one changed line
                       through a warm Renderer -- the steady-state cost a
                       running app pays every tick, and the headline
                       number now that the renderer memoizes raw lines
    to_lines           Canvas.to_lines run-coalescing alone
    input_decode       pumping ~64 KiB of mixed input (plain chars, CSI
                       arrows, SGR mouse reports, multi-byte UTF-8)
                       through term.read_key via an os.pipe

Usage:
    python3 benchmarks/bench.py                # human-readable table
    python3 benchmarks/bench.py --json         # machine-readable results
    python3 benchmarks/bench.py --smoke        # quick sanity run + floors
    python3 benchmarks/bench.py --size 200x60  # frame size (default 120x40)

Methodology: each scenario runs 5 warmups, then k=7 repeats of n
iterations; reported are the median and the min ms per iteration (the
input decoder reports events/s, where "best" is the max). min is the
least noisy estimator for a hot loop; the median guards against a lucky
outlier. Numbers are machine-specific: compare only runs from the same
machine.

Pure stdlib; imports only the `tui` package (never the app or tests).
"""

import argparse
import io
import json
import os
import statistics
import sys
import threading
import time

try:
    import tui
except ImportError:
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import tui

from tui import term, widgets
from tui.canvas import Canvas
from tui.theme import get_theme

WARMUPS = 5
REPEATS = 7
DECODE_TARGET = 64 * 1024  # ~64 KiB of raw input bytes

# Loose --smoke floors (upper bounds, ms/iteration) -- generous enough
# for any development machine; they catch order-of-magnitude regressions
# and total breakage, not percent-level drift.
SMOKE_MAX_MS = {
    "canvas_alloc": 25.0,
    "full_frame": 50.0,
    "incremental_frame": 25.0,
    "to_lines": 25.0,
}
SMOKE_MIN_EVENTS_PER_S = 20000.0


# ----------------------------------------------------------------------------
# Frame composition (dashboard-like: boxes, table, bars, sparkline)
# ----------------------------------------------------------------------------

TEAMS = (
    ("BRA", "Brazil", 0.91), ("FRA", "France", 0.84),
    ("ARG", "Argentina", 0.82), ("ENG", "England", 0.73),
    ("ESP", "Spain", 0.71), ("GER", "Germany", 0.62),
    ("POR", "Portugal", 0.55), ("NED", "Netherlands", 0.48),
    ("USA", "United States", 0.41), ("MEX", "Mexico", 0.33),
    ("JPN", "Japan", 0.28), ("KOR", "Korea Republic", 0.21),
)
SPARK = (3, 5, 2, 8, 7, 4, 9, 6, 1, 5, 8, 3, 7, 2, 6, 9, 4, 8, 5, 7)


def compose_frame(cols, rows, tick):
    """Draw a representative dashboard frame. `tick` only changes the
    status line (row rows-2), so consecutive ticks differ in exactly one
    rendered line -- the incremental_frame scenario depends on that."""
    t = get_theme()
    base = widgets.base_style()
    panel = widgets.panel_style()
    line = base + term.fg(*t.line)
    accent = base + term.fg(*t.accent) + term.BOLD
    dim = base + term.fg(*t.dim)
    hl = base + term.fg(*t.highlight)

    cv = Canvas(cols, rows, base)
    widgets.tab_bar(cv, 0, 0, cols,
                    [("1", "Overview"), ("2", "Matches"),
                     ("3", "Groups"), ("4", "Stats")],
                    0, hint="q quit")

    body_h = max(2, rows - 4)
    left_w = max(2, cols // 2 - 1)
    right_c = left_w + 1
    right_w = max(2, cols - right_c - 1)

    # Left: standings table in a box.
    cv.box(1, 0, body_h, left_w, style=line, title="Standings",
           title_style=accent)
    spec = [("TEAM", 5, "left"), ("NAME", -1, "left"),
            ("PTS", 4, "right"), ("GD", 4, "right")]
    table_rows = []
    for i, (code, name, frac) in enumerate(TEAMS):
        table_rows.append([(code, hl), (name, base),
                           (str(30 - i * 2), base), (str(9 - i), dim)])
    widgets.draw_table(cv, 2, 2, left_w - 4, spec, table_rows,
                       header_style=dim + term.BOLD)
    widgets.draw_rule(cv, min(rows - 4, 3 + len(TEAMS)), 2, left_w - 4,
                      title="form", style=line, title_style=dim)
    widgets.draw_sparkline(cv, min(rows - 3, 4 + len(TEAMS)), 2,
                           list(SPARK), style=accent)

    # Right: win-probability meters in a box.
    cv.box(1, right_c, body_h, right_w, style=line, title="Win probability",
           title_style=accent)
    bar_w = max(1, right_w - 16)
    for i, (code, name, frac) in enumerate(TEAMS):
        r = 2 + i
        if r >= rows - 4:
            break
        cv.put(r, right_c + 2, code, hl)
        fill = widgets.draw_hbar(cv, r, right_c + 8, bar_w, frac,
                                 accent, track_style=dim)
        cv.put(r, right_c + 8 + bar_w + 1, "%3d%%" % int(frac * 100), dim)
    widgets.draw_badge(cv, min(rows - 4, 3 + len(TEAMS)), right_c + 2,
                       "LIVE", term.bg(*t.error) + term.fg(*t.white))

    # Status line: the only row that varies with `tick`.
    cv.put(rows - 2, 1, "tick %06d  |  frame ok  |  %dx%d"
           % (tick, cols, rows), dim)
    widgets.footer(cv, rows - 1, 0, cols,
                   [("q", "quit"), ("r", "refresh"), ("tab", "next")],
                   right="tui %s" % tui.__version__)
    return cv


# ----------------------------------------------------------------------------
# Harness
# ----------------------------------------------------------------------------

def bench_loop(fn, n, repeats, warmups):
    """Return per-iteration times (seconds) for `repeats` timed runs."""
    for _ in range(warmups):
        fn()
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        samples.append((time.perf_counter() - t0) / n)
    return samples


def run_canvas_alloc(cols, rows, n, repeats, warmups):
    def fn():
        Canvas(cols, rows)
    return bench_loop(fn, n, repeats, warmups)


def run_full_frame(cols, rows, n, repeats, warmups):
    size = (cols, rows)

    def fn():
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            renderer = term.Renderer()
            cv = compose_frame(cols, rows, 0)
            renderer.render(cv.to_lines(), size)
        finally:
            sys.stdout = old
    return bench_loop(fn, n, repeats, warmups)


def run_incremental_frame(cols, rows, n, repeats, warmups):
    size = (cols, rows)
    frames = [compose_frame(cols, rows, k).to_lines() for k in (0, 1)]
    changed = sum(1 for a, b in zip(frames[0], frames[1]) if a != b)
    if changed != 1:
        raise AssertionError(
            "incremental fixture must differ in exactly 1 line, got %d"
            % changed)
    buf = io.StringIO()
    renderer = term.Renderer()
    state = [0]

    def fn():
        state[0] ^= 1
        buf.seek(0)
        buf.truncate()
        renderer.render(frames[state[0]], size)

    old = sys.stdout
    sys.stdout = buf
    try:
        renderer.render(frames[0], size)  # prime the diff/memo state
        return bench_loop(fn, n, repeats, warmups)
    finally:
        sys.stdout = old


def run_to_lines(cols, rows, n, repeats, warmups):
    cv = compose_frame(cols, rows, 0)

    def fn():
        cv.to_lines()
    return bench_loop(fn, n, repeats, warmups)


def build_decode_payload(target):
    """~`target` bytes cycling plain chars, CSI arrows, SGR mouse
    reports, and 2/3/4-byte UTF-8. Returns (payload, expected_events)."""
    pattern = (
        b"a", b"Z", b"9", b" ",
        b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D",
        b"\x1b[H", b"\x1b[5~", b"\x1b[3~",
        b"\x1b[<0;10;5M", b"\x1b[<0;10;5m",
        b"\x1b[<64;33;12M", b"\x1b[<2;80;24M",
        "é".encode("utf-8"),       # 2-byte
        "日".encode("utf-8"),       # 3-byte (CJK)
        "\U0001f389".encode("utf-8"),   # 4-byte (emoji)
    )
    chunks = []
    size = 0
    events = 0
    while size < target:
        for item in pattern:
            chunks.append(item)
            size += len(item)
            events += 1
    return b"".join(chunks), events


def _pipe_writer(wfd, payload):
    view = memoryview(payload)
    while view:
        written = os.write(wfd, view)
        view = view[written:]
    os.close(wfd)


def run_input_decode(n, repeats, warmups, payload):
    """Return (per-pump seconds, events decoded per pump)."""
    counted = [0]

    def pump():
        rfd, wfd = os.pipe()
        writer = threading.Thread(target=_pipe_writer, args=(wfd, payload))
        writer.start()
        count = 0
        try:
            while True:
                key = term.read_key(timeout=1.0, fd=rfd)
                if key is None:
                    break  # EOF: writer done and pipe drained
                count += 1
        finally:
            writer.join()
            os.close(rfd)
        counted[0] = count

    samples = bench_loop(pump, n, repeats, warmups)
    return samples, counted[0]


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def parse_size(text):
    parts = text.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("size must look like 120x40")
    try:
        cols, rows = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 120x40")
    if cols < 20 or rows < 10:
        raise argparse.ArgumentTypeError("minimum size is 20x10")
    return cols, rows


def collect(cols, rows, smoke):
    warmups = 1 if smoke else WARMUPS
    repeats = 1 if smoke else REPEATS
    counts = {
        "canvas_alloc": 10 if smoke else 100,
        "full_frame": 3 if smoke else 20,
        "incremental_frame": 20 if smoke else 200,
        "to_lines": 10 if smoke else 100,
        "input_decode": 1,
    }
    results = []

    def add_ms(name, samples):
        ms = [s * 1000.0 for s in samples]
        results.append({
            "name": name, "unit": "ms", "n": counts[name],
            "repeats": repeats,
            "median": statistics.median(ms), "best": min(ms),
        })

    add_ms("canvas_alloc",
           run_canvas_alloc(cols, rows, counts["canvas_alloc"],
                            repeats, warmups))
    add_ms("full_frame",
           run_full_frame(cols, rows, counts["full_frame"],
                          repeats, warmups))
    add_ms("incremental_frame",
           run_incremental_frame(cols, rows, counts["incremental_frame"],
                                 repeats, warmups))
    add_ms("to_lines",
           run_to_lines(cols, rows, counts["to_lines"], repeats, warmups))

    payload, expected = build_decode_payload(DECODE_TARGET)
    samples, decoded = run_input_decode(counts["input_decode"], repeats,
                                        warmups, payload)
    rates = [decoded / s for s in samples]
    results.append({
        "name": "input_decode", "unit": "events/s", "n": decoded,
        "repeats": repeats,
        "median": statistics.median(rates), "best": max(rates),
        "bytes": len(payload), "events_expected": expected,
    })
    return results


def check_smoke(results):
    failures = []
    for r in results:
        if r["unit"] == "ms":
            limit = SMOKE_MAX_MS[r["name"]]
            if r["median"] > limit:
                failures.append("%s: %.3f ms > %.1f ms floor"
                                % (r["name"], r["median"], limit))
        else:
            if r["median"] < SMOKE_MIN_EVENTS_PER_S:
                failures.append("%s: %.0f events/s < %.0f floor"
                                % (r["name"], r["median"],
                                   SMOKE_MIN_EVENTS_PER_S))
            if r["events_expected"] and not r["n"]:
                failures.append("input_decode: decoded 0 events")
    return failures


def fmt_value(r, key):
    if r["unit"] == "ms":
        return "%10.3f ms  " % r[key]
    return "%9.0f ev/s " % r[key]


def print_table(results, cols, rows):
    print("tui %s benchmark   size=%dx%d   python=%s"
          % (tui.__version__, cols, rows,
             ".".join(str(v) for v in sys.version_info[:3])))
    print("%-18s %-15s %-15s %s" % ("scenario", "median", "best", "n/repeat"))
    print("-" * 58)
    for r in results:
        print("%-18s %s %s %d" % (r["name"], fmt_value(r, "median"),
                                  fmt_value(r, "best"), r["n"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Benchmark the tui rendering and input primitives.")
    ap.add_argument("--smoke", action="store_true",
                    help="single quick repeat; assert loose perf floors")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON on stdout")
    ap.add_argument("--size", type=parse_size, default=(120, 40),
                    metavar="WxH", help="frame size (default 120x40)")
    args = ap.parse_args(argv)
    cols, rows = args.size

    # Pin the color depth so results don't depend on the caller's TERM.
    term.set_color_depth("truecolor")

    results = collect(cols, rows, args.smoke)

    if args.json:
        print(json.dumps({
            "version": tui.__version__,
            "python": ".".join(str(v) for v in sys.version_info[:3]),
            "size": {"cols": cols, "rows": rows},
            "smoke": args.smoke,
            "scenarios": results,
        }, indent=2))
    else:
        print_table(results, cols, rows)

    if args.smoke:
        failures = check_smoke(results)
        if failures:
            for f in failures:
                print("SMOKE FAIL  %s" % f, file=sys.stderr)
            return 1
        if not args.json:
            print("smoke: all scenarios completed within floors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
