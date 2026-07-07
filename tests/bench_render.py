"""
bench_render.py - Render-performance harness (not a unittest; run directly).

    python3 tests/bench_render.py [--json] [--only SCENARIO]

Full-frame renders of every offline view fixture (tests/fixtures_views.py)
at 120x40, plus the examples dashboard when it imports headlessly. Each
scenario gets 5 warmup frames, then 5 runs of 200 iterations; the reported
figure is the minimum ms/frame across runs (min is the least noisy estimator
for a hot loop). --json emits machine-readable results on stdout.

The pre-Region baseline lives in tests/goldens/bench_baseline.json; later
phases compare against it with a <=5% regression gate. Numbers are
machine-specific: compare only runs captured on the same machine.

Beware OS throttling: on Apple Silicon, scenarios executed later within one
long-running invocation measure 10-25% slow, so a full-suite run is NOT
comparable scenario-by-scenario against the baseline. For gate checks, run
one scenario per interpreter invocation (`--only SCENARIO`) on an idle
machine, and prefer an interleaved same-session A/B against the baseline
worktree over the stored numbers when the two disagree.
"""

import json
import os
import platform
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import fixtures_views as F
import wc

COLS, ROWS = 120, 40
WARMUPS = 5
RUNS = 5
ITERATIONS = 200

VIEW_FIXTURES = [
    ("live", F.state_live),
    ("live_palette", F.state_live_palette),
    ("schedule", F.state_schedule),
    ("groups", F.state_groups),
    ("bracket", F.state_bracket),
    ("bracket_scrolled", F.state_bracket_scrolled),
    ("scorers_goals", F.state_scorers_goals),
    ("scorers_assists", F.state_scorers_assists),
    ("detail_lineups", F.state_detail_lineups),
    ("detail_timeline", F.state_detail_timeline),
    ("detail_stats", F.state_detail_stats),
    ("detail_odds", F.state_detail_odds),
    ("team", F.state_team),
    ("help", F.state_help),
]


def view_scenario(build):
    """One reusable fixture app; frame re-pinned so every render is equal."""
    app = F.make_app(build)

    def fn():
        app.frame = F.FRAME  # render_frame() increments it
        wc.render_frame(app, COLS, ROWS)
    return fn


def dashboard_scenario():
    """examples/dashboard.py draw_frame + to_lines, or None if unimportable."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "examples"))
        import dashboard
        state = dashboard.ListState(len(dashboard.SERVICES), sel=2)
        dashboard.draw_frame(COLS, ROWS, 0, state)
    except Exception:
        return None

    def fn():
        dashboard.draw_frame(COLS, ROWS, 0, state).to_lines()
    return fn


def bench(fn):
    """Min ms/frame over RUNS timed runs of ITERATIONS frames each."""
    for _ in range(WARMUPS):
        fn()
    best = None
    for _ in range(RUNS):
        t0 = time.perf_counter()
        for _ in range(ITERATIONS):
            fn()
        dt = time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
    return best * 1000.0 / ITERATIONS


def main(argv):
    as_json = "--json" in argv
    scenarios = [(name, view_scenario(build)) for name, build in VIEW_FIXTURES]
    dash = dashboard_scenario()
    if dash is not None:
        scenarios.append(("dashboard", dash))
    if "--only" in argv:
        i = argv.index("--only")
        only = argv[i + 1] if i + 1 < len(argv) else ""
        scenarios = [(n, fn) for n, fn in scenarios if n == only]
        if not scenarios:
            sys.stderr.write("unknown scenario: %r\n" % only)
            return 2

    results = {}
    for name, fn in scenarios:
        results[name] = bench(fn)
        if not as_json:
            print("%-20s %8.3f ms/frame" % (name, results[name]))
    total = sum(results.values())

    if as_json:
        payload = {
            "meta": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "size": "%dx%d" % (COLS, ROWS),
                "warmups": WARMUPS,
                "runs": RUNS,
                "iterations": ITERATIONS,
                "metric": "min ms/frame across runs",
                "note": "numbers are machine-specific; compare only "
                        "against a baseline captured on the same machine",
            },
            "scenarios": results,
            "total_ms_per_frame": total,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("%-20s %8.3f ms/frame" % ("TOTAL", total))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
