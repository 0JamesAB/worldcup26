#!/usr/bin/env python3
"""
logtail.py - Log viewer demo of the tui app kit (v0.5.0), detached from
the World Cup app: App (view stack, keymaps, capture, toasts),
select_list over col_layout columns, a text_pane modal (Esc pops via the
kit built-in - this file has no Esc handler), a LineEdit '/' filter with
a ghost completion, and a tiny ':' CommandSet/Palette. A seeded producer
thread appends records under app.lock + invalidate(); ERROR lines toast.

Keys: up/down move (drops follow) · f follow · g/G home/end ·
Enter open entry · / filter · : command · q quit.

    python3 examples/logtail.py [--seed N]
    python3 examples/logtail.py --snapshot 100x30   # one frame, no TTY
"""

import os
import random
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import puretui
from puretui import term, widgets
from puretui.app import App
from puretui.canvas import Canvas
from puretui.commands import CommandSet, Palette, draw_palette_bar, draw_palette_menu
from puretui.interact import LineEdit, ListState, ScrollState
from puretui.layout import Fixed, Flex
from puretui.term import BOLD, Key, bg, fg
from puretui.theme import Theme

MIN_COLS, MIN_ROWS = 60, 12
DEFAULT_SEED = 2026
PREFILL = 120
LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
SERVICES = ("api-gateway", "auth", "billing", "search", "ingest", "notify")
MESSAGES = {
    "DEBUG": ("cache miss key=user:{n}", "retry backoff {n}ms for {svc}",
              "gc pause {n}ms"),
    "INFO": ("GET /v1/{svc} 200 in {n}ms", "worker {svc} heartbeat ok",
             "flushed {n} rows to {svc}"),
    "WARN": ("slow query {n}ms on {svc}", "queue depth {n} on {svc}",
             "{svc} p99 above budget ({n}ms)"),
    "ERROR": ("upstream {svc} timed out after {n}ms",
              "connection refused by {svc}",
              "unhandled exception in {svc} worker"),
}


class LogState:
    """Everything the views draw: records, cursors, filter, entry."""

    def __init__(self, seed=DEFAULT_SEED):
        self.rng = random.Random(seed)
        self.clock = 0.0            # synthetic seconds since 09:00:00
        self.records = []           # (t, level, msg), newest last
        self.ls = ListState()
        self.follow = True
        self.filter_text = ""
        self.min_level = 0          # index into LEVELS
        self.filtering = False
        self.edit = LineEdit()
        self.entry = None           # (record, context records)
        self.entry_scroll = ScrollState()
        self.pal = None
        self.open_entry = None      # set by build_app; select_list on_open


def make_record(st):
    """Advance the synthetic clock and mint one deterministic record."""
    rng = st.rng
    st.clock += rng.uniform(0.2, 2.4)
    lvl = rng.choices(LEVELS, weights=(28, 50, 13, 9))[0]
    msg = rng.choice(MESSAGES[lvl]).format(svc=rng.choice(SERVICES),
                                           n=rng.randrange(2, 950))
    return (st.clock, lvl, msg)


def fmt_ts(t):
    s = int(t)
    return "%02d:%02d:%02d" % (9 + s // 3600, (s // 60) % 60, s % 60)


def rate(st):
    """Records per synthetic second over the trailing 10s window."""
    cut = st.clock - 10.0
    return sum(1 for r in st.records if r[0] >= cut) / 10.0


def filtered(st):
    """Records passing the :level floor and the '/' substring filter."""
    recs = st.records
    if st.min_level:
        recs = [r for r in recs if LEVELS.index(r[1]) >= st.min_level]
    f = st.filter_text.lower()
    if f:
        recs = [r for r in recs if f in r[1].lower() or f in r[2].lower()]
    return recs


def ghost_for(buf):
    """Remainder of the level name `buf` is a prefix of, or ''."""
    b = buf.strip().upper()
    if b:
        for lvl in LEVELS:
            if lvl.startswith(b) and lvl != b:
                return lvl[len(b):]
    return ""


def level_styles(t):
    return {"DEBUG": fg(*t.faint), "INFO": fg(*t.accent2),
            "WARN": fg(*t.warn), "ERROR": fg(*t.error) + BOLD}


# ---------------------------------------------------------------------------
# Views (the app owns every pixel; the kit never draws)
# ---------------------------------------------------------------------------

def draw_tail(root, app):
    st = app.state
    t = Theme
    if root.w < MIN_COLS or root.h < MIN_ROWS:
        root.put(0, 0, "Terminal too small (%dx%d); need at least %dx%d."
                 % (root.w, root.h, MIN_COLS, MIN_ROWS))
        return
    header, body, footer = root.split_v(Fixed(2), Flex(1), Fixed(1))
    recs = filtered(st)
    if st.follow:
        st.ls.set_count(len(recs))
        st.ls.end()

    # -- header: name · volume · rate · filter chips · FOLLOW badge --------
    hd = (header.at(0, 1).write("LOGTAIL", fg(*t.text) + BOLD).gap(2)
                .write(" %d lines " % len(st.records), bg(*t.bg2) + fg(*t.dim))
                .gap(1).write("%.1f/s" % rate(st), fg(*t.accent2)))
    if st.min_level:
        hd.gap(2).write(" %s+ " % LEVELS[st.min_level], bg(*t.bg2) + fg(*t.warn))
    if st.filter_text:
        hd.gap(1).write(" /%s " % st.filter_text, bg(*t.bg2) + fg(*t.highlight))
    if st.follow:
        header.right(" FOLLOW ", bg(*t.accent) + fg(*t.bg0) + BOLD, pad=1)
    elif recs:
        header.right("%d/%d" % (st.ls.sel + 1, len(recs)), fg(*t.dim), pad=1)
    header.rule(r=1, style=fg(*t.line))

    # -- body: TIME | LVL | MESSAGE over a select_list ----------------------
    body = body.inset(0, 1)
    cols_spec = [("TIME", 10, "left"), ("LVL", 7, "left"), ("MESSAGE", -1, "left")]
    body.table(cols_spec, [], header_style=fg(*t.faint) + BOLD)
    (ts_x, _), (lv_x, _), (ms_x, ms_w) = widgets.col_layout(cols_spec, body.w)
    lvl_st = level_styles(t)

    def draw_rec(row, rec, i, sel):
        tt, lvl, msg = rec
        row_bg = bg(*t.bg2) if sel else ""
        if sel:
            row.fill(row_bg)
        row.put(0, ts_x, fmt_ts(tt), row_bg + fg(*t.dim))
        row.put(0, lv_x, lvl, row_bg + lvl_st[lvl])
        row.put(0, ms_x, msg, row_bg + (fg(*t.white) + BOLD if sel
                                        else fg(*t.text)), max_w=ms_w)

    body.region(1).select_list(recs, st.ls, draw_rec,
                               on_open=lambda rec, i: st.open_entry())
    if not recs:
        body.center("no matching records", fg(*t.faint), r=2)

    # -- toast (newest only, drawn app-side above the footer) --------------
    toast = app.toasts.latest()
    if toast is not None and toast.alive:
        color = t.error if toast.kind == "error" else t.accent
        root.right(" " + toast.text + " ", bg(*color) + fg(*t.bg0) + BOLD,
                   r=root.h - 2, pad=1)

    # -- footer: palette bar, filter input, or key hints --------------------
    pal = st.pal
    if pal is not None and pal.open:
        draw_palette_bar(footer, pal)
        draw_palette_menu(root, pal)
    elif st.filtering:
        footer.fill(bg(*t.bg1))
        footer.region(0, 1).input(st.edit, prompt="/",
                                  style=bg(*t.bg1) + fg(*t.white) + BOLD,
                                  ghost=ghost_for(st.edit.text))
    else:
        widgets.footer(footer, 0, 0, footer.w,
                       [("↑↓", "move"), ("f", "follow"), ("Enter", "open"),
                        ("/", "filter"), (":", "cmd"), ("q", "quit")],
                       right="logtail · tui " + puretui.__version__, theme=t)


def draw_entry(root, app):
    """The 'entry' view: the tail behind a modal of the full record."""
    draw_tail(root, app)
    st = app.state
    t = Theme
    if st.entry is None or root.w < MIN_COLS or root.h < MIN_ROWS:
        return
    (tt, lvl, msg), ctx = st.entry
    h = max(8, min(root.h - 4, 7 + len(ctx)))
    w = min(root.w - 8, 76)
    panel = bg(*t.bg1)
    inner = root.modal(h, w, title="log entry", style=fg(*t.accent2),
                       fill_style=panel)
    lines = [("%s  %s" % (fmt_ts(tt), lvl), panel + level_styles(t)[lvl]),
             (msg, panel + fg(*t.text)), ("", panel),
             ("context", panel + fg(*t.faint))]
    lines += [("%s  %-5s  %s" % (fmt_ts(ct), cl, cm), panel + fg(*t.dim))
              for ct, cl, cm in ctx]
    inner.inset(0, 1).text_pane(lines, st.entry_scroll, pct=True,
                                style=panel + fg(*t.text),
                                pct_style=panel + fg(*t.faint))


def draw_frame(root, app):
    app.views[app.view].render(root, app)


# ---------------------------------------------------------------------------
# Wiring (the wc.py idiom: views + keymaps + palette on the App kit)
# ---------------------------------------------------------------------------

def build_app(st):
    app = App(state=st, fps=10, tick=0.5)

    def move(d):
        st.follow = False
        st.ls.move(d)

    def toggle_follow():
        st.follow = not st.follow
        if st.follow:
            st.ls.end()

    def home():
        st.follow = False
        st.ls.home()

    def open_entry():
        recs = filtered(st)
        if not recs:
            return
        rec = recs[max(0, min(st.ls.sel, len(recs) - 1))]
        i = st.records.index(rec)
        st.entry = (rec, st.records[max(0, i - 2):i + 3])
        st.entry_scroll = ScrollState()
        if app.view != "entry":
            app.push("entry")

    def open_filter():
        st.edit = LineEdit(st.filter_text)
        st.filtering = True

        def cap(key):
            if key == Key.ENTER:
                st.filter_text = st.edit.text.strip()
                close()
                app.toast("%d matches" % len(filtered(st)), "info", 4)
            elif key == Key.ESC:
                close()
            elif key == Key.TAB:
                g = ghost_for(st.edit.text)
                if g:
                    st.edit.buf = st.edit.text.strip().upper() + g
                    st.edit.cursor = len(st.edit.buf)
            else:
                st.edit.handle_key(key)
            return True

        def close():
            st.filtering = False
            app.capture = None

        app.capture = cap

    st.open_entry = open_entry
    app.add_view("tail", draw_tail,
                 keys={(Key.UP, "k"): lambda: move(-1),
                       (Key.DOWN, "j"): lambda: move(1),
                       ("g", Key.HOME): home,
                       ("G", Key.END): st.ls.end,
                       "f": toggle_follow,
                       Key.ENTER: open_entry,
                       "/": open_filter},
                 on_wheel=move)
    # NOTE: no Esc handler anywhere - the kit's built-in pops "entry".
    app.add_view("entry", draw_entry,
                 keys={(Key.UP, "k"): lambda: st.entry_scroll.scroll(-1),
                       (Key.DOWN, "j"): lambda: st.entry_scroll.scroll(1),
                       ("g", Key.HOME): lambda: st.entry_scroll.home(),
                       ("G", Key.END): lambda: st.entry_scroll.end()},
                 on_wheel=st.entry_scroll.scroll)

    def do_follow(arg):
        toggle_follow()
        return "follow " + ("on" if st.follow else "off")

    def do_level(arg):
        lvl = arg.strip().upper()
        if lvl not in LEVELS:
            return "unknown level: %s (try %s)" % (arg, "/".join(LEVELS))
        st.min_level = LEVELS.index(lvl)
        return "showing %s and above" % lvl

    def do_clear(arg):
        with app.lock:
            del st.records[:]
        return "cleared"

    def complete_level(arg):
        pre = arg.strip().upper()
        rows = [{"text": "level " + lv, "label": ":level " + lv,
                 "hint": "floor at " + lv, "kind": "arg"}
                for lv in LEVELS if lv.startswith(pre)]
        return ("Levels", rows)

    pal = Palette(CommandSet([
        {"name": "follow", "aliases": ["f"], "syntax": "follow",
         "desc": "toggle follow mode", "run": do_follow},
        {"name": "level", "aliases": ["lvl"], "syntax": "level <LEVEL>",
         "desc": "hide records below LEVEL", "run": do_level,
         "complete": complete_level},
        {"name": "clear", "aliases": [], "syntax": "clear",
         "desc": "drop all records", "run": do_clear},
        {"name": "quit", "aliases": ["q"], "syntax": "quit",
         "desc": "exit logtail", "run": lambda a: app.quit() or ""},
    ]), on_status=lambda msg: app.toast(msg, "info", 4))
    st.pal = pal

    app.bind({("q", "Q"): app.quit, ":": lambda: pal.open_(app)})
    app.goto("tail")
    return app


def producer(app, st, stop):
    """Seeded background feed: mutate under app.lock, then invalidate."""
    while app.running and not stop.is_set():
        stop.wait(st.rng.uniform(0.15, 0.6))
        with app.lock:
            rec = make_record(st)
            st.records.append(rec)
            del st.records[:-5000]
        if rec[1] == "ERROR":
            app.toast(rec[2], "error", 6)
        app.invalidate()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def render_frame(app, cols, rows):
    """One frame (list of ANSI lines) without entering the terminal."""
    with app.lock:
        app.frame += 1
        app.hits.clear()
        cv = Canvas(cols, rows, widgets.base_style())
        draw_frame(cv.region(hits=app.hits), app)
        return cv.to_lines()


def snapshot(spec, seed):
    """Render one deterministic frame to stdout (no TTY, no thread)."""
    try:
        c, r = spec.lower().split("x")
        cols, rows = int(c), int(r)
    except ValueError:
        cols, rows = 100, 30
    st = LogState(seed)
    st.records = [make_record(st) for _ in range(PREFILL)]
    app = build_app(st)
    lines = render_frame(app, cols, rows)
    sys.stdout.write("\n".join(lines) + term.RESET + "\n")


def main(argv):
    seed = DEFAULT_SEED
    if "--seed" in argv:
        i = argv.index("--seed")
        if i + 1 < len(argv):
            seed = int(argv[i + 1])
    if "--snapshot" in argv:
        i = argv.index("--snapshot")
        snapshot(argv[i + 1] if i + 1 < len(argv) else "100x30", seed)
        return 0
    if not sys.stdin.isatty():
        print("logtail: needs an interactive terminal (or use --snapshot WxH).")
        return 1

    st = LogState(seed)
    st.records = [make_record(st) for _ in range(PREFILL)]
    app = build_app(st)
    stop = threading.Event()
    threading.Thread(target=producer, args=(app, st, stop), daemon=True).start()
    app.run(draw_frame)
    stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
