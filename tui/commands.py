"""
commands.py - Optional command-palette kit: a command registry with
completion (CommandSet), a vim-style ':' prompt driven through app.capture
(Palette), and the two drawing ports (draw_palette_bar, draw_palette_menu).

A command spec is a plain dict:

    name      canonical command name
    aliases   list of alternate names (may be empty)
    syntax    one-line usage, e.g. "team <name|ABBR>". A space in the
              syntax marks the command as argument-taking (its completion
              text gets a trailing space so typing flows into the arg).
    desc      short description for menus / help
    run       callable(arg_str) -> status string
    complete  None, or callable(arg_str) -> (title, suggestions) for
              argument completion. None falls back to a single info row
              showing the command's syntax.

A suggestion is a dict {text, label, hint, kind}: `text` is the full
command buffer (without the leading ':') installed when the suggestion
is accepted with Tab; `kind` is "cmd" | "arg" | "info".

The drawing functions are ports of the host app's statusline command
branch and floating suggestion menu, parameterized only by theme colors.
Color mapping from the app palette: bg0/bg1/bg2/text/dim/faint/white/
accent/accent2 map by name; the app's `gold` (title + emphasis) maps to
`theme.highlight` (identical RGB in the app theme, so output stays
byte-identical). This module never imports app code.
"""

from . import term
from .canvas import LIGHT
from .interact import LineEdit
from .term import Key
from .theme import get_theme

__all__ = ["CommandSet", "Palette", "draw_palette_bar", "draw_palette_menu"]


class CommandSet:
    """A registry of command specs: lookup, completion, dispatch, help."""

    def __init__(self, specs):
        self.specs = list(specs)

    def find(self, tok):
        """The spec matching `tok` by name, alias, or unique prefix."""
        tok = tok.lower()
        for c in self.specs:
            if tok == c["name"] or tok in c["aliases"]:
                return c
        # unique prefix match
        hits = [c for c in self.specs
                if c["name"].startswith(tok) or any(a.startswith(tok) for a in c["aliases"])]
        return hits[0] if len(hits) == 1 else None

    def completions(self, buf):
        """Return (title, suggestions) for the current command buffer.

        Before the first space: the command menu, prefix-filtered over
        names and aliases. After it: the command's `complete` provider
        (called with the stripped argument text), or a single info row
        showing its syntax.
        """
        if " " not in buf:
            prefix = buf.strip().lower()
            out = []
            for c in self.specs:
                names = [c["name"]] + c["aliases"]
                if prefix == "" or any(n.startswith(prefix) for n in names):
                    text = c["name"] + (" " if " " in c["syntax"] else "")
                    out.append({"text": text, "label": ":" + c["syntax"],
                                "hint": c["desc"], "kind": "cmd"})
            return ("Commands", out)

        toks = buf.split(" ", 1)
        cmd = self.find(toks[0])
        if not cmd:
            return ("?", [])
        arg = (toks[1] if len(toks) > 1 else "").strip()
        complete = cmd.get("complete")
        if complete is not None:
            return complete(arg)
        return (cmd["syntax"], [{"text": buf, "label": ":" + cmd["syntax"],
                                 "hint": cmd["desc"], "kind": "info"}])

    def run(self, raw):
        """Execute a command line (leading ':' optional); returns status.

        The command token resolves through find(), so unique prefixes
        run too. Unknown commands report "unknown: X  (try :help)".
        """
        raw = raw.strip()
        if raw.startswith(":"):
            raw = raw[1:]
        if not raw:
            return ""
        parts = raw.split()
        cmd = self.find(parts[0])
        if cmd is None:
            return f"unknown: {parts[0].lower()}  (try :help)"
        return cmd["run"](" ".join(parts[1:]))

    def help_rows(self):
        """(":syntax", desc) pairs for a help screen."""
        return [(":" + c["syntax"], c["desc"]) for c in self.specs]


class Palette:
    """Vim-style ':' prompt state, driven through `app.capture`.

    open_(app) installs the palette's key handler as the app's capture;
    every key is consumed until Enter runs the buffer (the palette
    closes first, then the status string is reported through on_status)
    or Esc cancels. Tab fills the buffer with the highlighted
    suggestion; Up / Shift-Tab / Down move the highlight with
    wraparound; everything else feeds the LineEdit, and any buffer
    change resets the highlight to the first suggestion.
    """

    def __init__(self, commands, on_status=None):
        self.commands = commands
        self.on_status = on_status
        self.open = False
        self.edit = LineEdit()
        self.sel = 0
        self._app = None

    def open_(self, app):
        """Open the prompt: clear the buffer and grab the app's keys."""
        self._app = app
        self.open = True
        self.edit.clear()
        self.sel = 0
        app.capture = self._key

    def close(self, app):
        """Close the prompt and release the key capture."""
        self.open = False
        self.edit.clear()
        self.sel = 0
        if app is not None and getattr(app, "capture", None) == self._key:
            app.capture = None

    def _key(self, key):
        """Key capture while the prompt is open. Consumes every key."""
        if key == Key.ENTER:
            raw = self.edit.text
            self.close(self._app)
            res = self.commands.run(raw)
            if res and self.on_status is not None:
                self.on_status(res)
        elif key == Key.ESC:
            self.close(self._app)
        elif key == Key.TAB:
            self._complete()
        elif key in (Key.UP, Key.SHIFT_TAB):
            self._move_sel(-1)
        elif key == Key.DOWN:
            self._move_sel(1)
        else:
            before = self.edit.buf
            self.edit.handle_key(key)
            if self.edit.buf != before:
                self.sel = 0
        return True

    def _complete(self):
        """Tab: fill the buffer with the highlighted suggestion."""
        _, sugg = self.commands.completions(self.edit.buf)
        if not sugg:
            return
        s = sugg[min(self.sel, len(sugg) - 1)]
        self.edit.buf = s["text"]
        self.edit.cursor = len(self.edit.buf)
        self.sel = 0

    def _move_sel(self, delta):
        """Move the suggestion highlight, wrapping around."""
        _, sugg = self.commands.completions(self.edit.buf)
        n = len(sugg)
        if n:
            self.sel = (self.sel + delta) % n


def draw_palette_bar(region, palette, theme=None):
    """The ':' prompt line, drawn into a one-row status `region`.

    Port of the app statusline's command branch: panel fill, bold-white
    prompt, block cursor, and a faint inline ghost of the highlighted
    suggestion with a "⇥ tab" hint. When the LineEdit cursor sits
    mid-buffer (a capability the original lacked), the character under
    it is drawn reversed instead of the trailing block.
    """
    t = theme if theme is not None else get_theme()
    buf = palette.edit.buf
    region.fill(term.bg(*t.bg1))
    white_b = term.bg(*t.bg1) + term.fg(*t.white) + term.BOLD
    prompt = ":" + buf
    region.put(0, 1, prompt, white_b)
    x = 1 + term.display_width(prompt)
    if palette.edit.cursor >= len(buf):
        region.put(0, x, "█", term.bg(*t.bg1) + term.fg(*t.accent))
    else:
        cx = 1 + term.display_width(":" + buf[:palette.edit.cursor])
        region.put(0, cx, buf[palette.edit.cursor], white_b + term.REVERSE)
    # inline ghost completion of the highlighted suggestion
    _, sugg = palette.commands.completions(buf)
    if sugg:
        text = sugg[min(palette.sel, len(sugg) - 1)]["text"]
        if text.startswith(buf) and len(text) > len(buf):
            ghost = text[len(buf):]
            faint = term.bg(*t.bg1) + term.fg(*t.faint)
            region.put(0, x + 1, term.strip_ansi(ghost), faint)
            region.put(0, x + 1 + term.display_width(ghost), "  ⇥ tab", faint)


def draw_palette_menu(root, palette, theme=None):
    """Floating suggestion menu above the ':' prompt, on the full-frame
    `root` region. Port of the app's command palette, with a popup-style
    click-swallowing hit over the box so hits under it are dead."""
    t = theme if theme is not None else get_theme()
    title, sugg = palette.commands.completions(palette.edit.buf)
    if not sugg:
        return
    palette.sel = max(0, min(palette.sel, len(sugg) - 1))
    status_row = root.h - 2
    top_limit = 3  # don't cover header / tabs / context strip
    maxshow = max(1, min(len(sugg), status_row - top_limit - 1, 10))
    # keep the highlighted row within the visible window
    win_start = 0
    if palette.sel >= maxshow:
        win_start = palette.sel - maxshow + 1
    shown = sugg[win_start:win_start + maxshow]

    def rw(s):
        return term.display_width(s["label"]) + term.display_width(s["hint"]) + 8
    w = min(root.w - 4, max(48, term.display_width(title) + 8, max(rw(s) for s in shown)))
    h = len(shown) + 2
    y0 = status_row - h
    x0 = 1
    root.box(y0, x0, h, w, style=term.fg(*t.accent2), chars=LIGHT, title=title,
             title_style=term.fg(*t.highlight) + term.BOLD,
             fill_style=term.bg(*t.bg2))
    root.hit(lambda: None, y0, x0, h, w)
    if len(sugg) > len(shown):
        more = f"{palette.sel + 1}/{len(sugg)}"
        root.put(y0, x0 + w - term.display_width(more) - 2, more,
                 term.bg(*t.bg2) + term.fg(*t.faint))
    for i, s in enumerate(shown):
        rr = y0 + 1 + i
        sel = (win_start + i) == palette.sel
        if sel:
            root.fill_rect(rr, x0 + 1, 1, w - 2, term.bg(*t.accent2))
            root.put(rr, x0 + 1, " ▸ ", term.bg(*t.accent2) + term.fg(*t.bg0) + term.BOLD)
            lblst = term.bg(*t.accent2) + term.fg(*t.bg0) + term.BOLD
            hintst = term.bg(*t.accent2) + term.fg(*t.bg0)
        else:
            lblst = term.bg(*t.bg2) + term.fg(*t.text)
            hintst = term.bg(*t.bg2) + term.fg(*t.dim)
        root.put(rr, x0 + 4, s["label"], lblst, max_w=w - 10)
        hint = s.get("hint", "")
        if hint:
            hx = x0 + w - term.display_width(hint) - 2
            if hx > x0 + 4 + term.display_width(s["label"]) + 1:
                root.put(rr, hx, term.strip_ansi(hint), hintst)
