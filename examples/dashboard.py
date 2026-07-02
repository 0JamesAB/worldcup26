#!/usr/bin/env python3
"""
dashboard.py - Self-contained demo of the tui library (v0.3.0 APIs).

A fake "fleet operations" dashboard that composes the new pieces:

    tui.run            frame loop (arrows move the selection, q quits)
    Region             local-coordinate, hard-clipped drawing surfaces
    split_v / split_h  flexbox-style layout, straight to child Regions
    at/write/gap       flowing cursor (header badges)
    right()            right-aligned text (spinner)
    table/spark/       widget sugar on Region; the sparkline column is
    progress/rule      a clipped sub-Region, no alignment arithmetic
    ListState          clamped cursor + scroll window over the services
    spinner            animated "polling" indicator

Run it interactively from the repo root:

    python3 examples/dashboard.py

Or render a single frame without a TTY (mirrors wc.py --snapshot):

    python3 examples/dashboard.py --snapshot 100x30
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tui
from tui import term, widgets
from tui.canvas import Canvas
from tui.interact import ListState
from tui.layout import Fixed, Flex
from tui.term import BOLD, Key, bg, fg
from tui.theme import Theme
from tui.widgets import spinner

MIN_COLS, MIN_ROWS = 60, 15

# ---------------------------------------------------------------------------
# Fake fleet data (deterministic, so snapshots are reproducible)
# ---------------------------------------------------------------------------

SERVICES = [
    # name, region, status, p50 ms, latency history (ms)
    ("api-gateway", "iad", "OK", 24, [22, 25, 23, 28, 24, 26, 21, 24, 27, 23, 25, 24]),
    ("auth", "iad", "OK", 11, [12, 11, 10, 13, 11, 12, 10, 11, 12, 11, 10, 11]),
    ("billing", "fra", "WARN", 87, [40, 44, 52, 61, 70, 76, 81, 90, 95, 88, 84, 87]),
    ("search", "sin", "OK", 33, [35, 31, 30, 36, 33, 32, 34, 30, 31, 35, 33, 33]),
    ("ingest", "iad", "OK", 18, [20, 17, 19, 16, 18, 21, 17, 18, 19, 16, 18, 18]),
    ("ml-ranker", "fra", "DOWN", 0, [64, 66, 71, 80, 92, 120, 160, 240, 0, 0, 0, 0]),
    ("notify", "sin", "OK", 29, [28, 30, 27, 31, 29, 28, 30, 29, 27, 31, 30, 29]),
    ("archive", "iad", "OK", 51, [49, 52, 50, 54, 51, 48, 53, 50, 52, 49, 51, 51]),
]

METERS = [
    ("CPU", 0.62),
    ("Memory", 0.48),
    ("Disk", 0.83),
    ("Network", 0.27),
]

DEPLOY = [
    ("v2.14.0", "api-gateway", "done"),
    ("v2.14.0", "auth", "done"),
    ("v2.14.0", "billing", "rolling"),
    ("v2.13.9", "ml-ranker", "held"),
]


def status_style(t, status):
    if status == "OK":
        return bg(*t.accent) + fg(*t.bg0) + BOLD
    if status == "WARN":
        return bg(*t.warn) + fg(*t.bg0) + BOLD
    return bg(*t.error) + fg(*t.white) + BOLD


# ---------------------------------------------------------------------------
# Frame rendering
# ---------------------------------------------------------------------------

def draw_frame(cols, rows, frame, state):
    t = Theme
    base = widgets.base_style(t)
    cv = Canvas(cols, rows, base)

    if cols < MIN_COLS or rows < MIN_ROWS:
        cv.put(0, 0, f"Terminal too small ({cols}x{rows}); "
                     f"need at least {MIN_COLS}x{MIN_ROWS}.", base)
        return cv

    header, body, footer = cv.region().split_v(Fixed(2), Flex(1), Fixed(1))

    # -- header ------------------------------------------------------------
    (header.at(0, 1).write("FLEET OPS", fg(*t.text) + BOLD).gap(2)
           .write(" prod ", bg(*t.accent2) + fg(*t.bg0) + BOLD).gap(1)
           .write(" 3 regions ", bg(*t.bg2) + fg(*t.dim)))
    header.right(spinner(frame) + " polling", fg(*t.accent), pad=1)
    header.rule(r=1, style=fg(*t.line))

    # -- body: services table | side column --------------------------------
    left, side = body.inset(0, 1).split_h(Flex(3, min=40), Flex(2, min=24),
                                          gap=2)

    left.rule(title="services", style=fg(*t.line),
              title_style=fg(*t.dim) + BOLD)
    visible = max(1, left.h - 2)
    start, stop = state.window(visible)
    spark_w = 12
    cols_spec = [("SERVICE", 15, "left"), ("REG", 5, "left"),
                 ("ST", 6, "left"), ("P50", 7, "right"),
                 (f"{'LAST 12':>{spark_w}}", -1, "right")]
    table_rows = []
    for i in range(start, stop):
        name, region, status, p50, _hist = SERVICES[i]
        sel = (i == state.sel)
        row_bg = bg(*t.bg2) if sel else ""
        txt = fg(*t.white) + BOLD if sel else fg(*t.text)
        mark = "▸ " if sel else "  "
        table_rows.append([
            (mark + name, row_bg + txt),
            (region, row_bg + fg(*t.dim)),
            (status, row_bg + status_style(t, status)),
            (f"{p50}ms" if p50 else "--", row_bg + fg(*t.dim)),
            None,  # sparkline drawn separately below
        ])
    left.table(cols_spec, table_rows, r=1, header_style=fg(*t.faint) + BOLD)
    # The sparkline column is its own clipped sub-Region past the fixed
    # columns: drawing right-aligned inside it can never overwrite the P50
    # column, and a too-narrow panel just clips the history's left edge.
    fixed_w = sum(cw for _, cw, _ in cols_spec if cw >= 0)
    sparks = left.region(2, fixed_w)
    for row_i, i in enumerate(range(start, stop)):
        hist = SERVICES[i][4]
        sel_bg = bg(*t.bg2) if i == state.sel else ""
        color = t.error if SERVICES[i][2] == "DOWN" else t.accent2
        sparks.spark(hist, r=row_i, c=sparks.w - len(hist),
                     style=sel_bg + fg(*color), lo=0)

    # -- side column: meters + deploys --------------------------------------
    meters, deploys = side.split_v(Fixed(2 + len(METERS)), Flex(1), gap=1)
    meters.rule(title="node capacity", style=fg(*t.line),
                title_style=fg(*t.dim) + BOLD)
    label_w = 9
    for i, (label, frac) in enumerate(METERS):
        meters.put(1 + i, 0, label, fg(*t.dim))
        color = t.error if frac > 0.8 else t.warn if frac > 0.6 else t.accent
        meters.progress(frac, fg(*color), r=1 + i, c=label_w,
                        track_style=fg(*t.bg2), show_pct=True,
                        pct_style=fg(*t.text))

    deploys.rule(title="deploys", style=fg(*t.line),
                 title_style=fg(*t.dim) + BOLD)
    dep_spec = [("TAG", 9, "left"), ("TARGET", -1, "left"), ("", 8, "right")]
    dep_rows = [[(tag, fg(*t.text)), (target, fg(*t.dim)),
                 (phase, fg(*t.accent) if phase == "done" else fg(*t.warn))]
                for tag, target, phase in DEPLOY]
    deploys.table(dep_spec, dep_rows, r=1, header_style=fg(*t.faint) + BOLD)

    # -- footer -------------------------------------------------------------
    sel_name = SERVICES[state.sel][0]
    widgets.footer(footer, 0, 0, footer.w,
                   [("↑↓", "select"), ("q", "quit")],
                   right=f"{sel_name}  ·  tui {tui.__version__}", theme=t)
    return cv


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def snapshot(spec):
    """Render one frame to stdout without a TTY and exit 0."""
    try:
        c, r = spec.lower().split("x")
        cols, rows = int(c), int(r)
    except ValueError:
        cols, rows = 100, 30
    state = ListState(len(SERVICES), sel=2)
    cv = draw_frame(cols, rows, 0, state)
    sys.stdout.write("\n".join(cv.to_lines()) + term.RESET + "\n")


def main(argv):
    if "--snapshot" in argv:
        i = argv.index("--snapshot")
        spec = argv[i + 1] if i + 1 < len(argv) else "100x30"
        snapshot(spec)
        return 0
    if not sys.stdin.isatty():
        print("dashboard: needs an interactive terminal "
              "(or use --snapshot WxH).")
        return 1

    state = ListState(len(SERVICES))

    def render(cols, rows, frame):
        return draw_frame(cols, rows, frame, state).to_lines()

    def on_key(key):
        if key in ("q", "Q", Key.ESC):
            return False
        if key == Key.UP:
            state.move(-1)
        elif key == Key.DOWN:
            state.move(1)
        elif key == Key.HOME:
            state.home()
        elif key == Key.END:
            state.end()
        return True

    tui.run(render, on_key=on_key, fps=10)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
