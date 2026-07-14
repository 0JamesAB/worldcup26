"""Property-based invariants for the width-aware text utilities.

A fixed corpus of seeded random strings (random.Random(0xF00D)) mixing
ASCII, CJK wide characters, combining marks, emoji, and injected SGR
escape sequences is pushed through term.truncate / term.pad / term.wrap,
asserting the invariants every caller (Canvas, Renderer, widgets) relies
on:

  a. display_width(truncate(s, w)) <= w for w in 0..40
  b. pad(s, w) is exactly w columns when s fits
  c. every line of wrap(s, w) fits in w columns
  d. ANSI SGR sequences are never split by any of the three
  e. visible characters survive: truncate/pad keep a prefix (with
     ellipsis), wrap is a whitespace rearrangement

Documented exemptions where the implementation intentionally deviates:

  * truncate(s, 0) of a string with visible content still emits the
    ellipsis marker (display width 1, not 0).
  * a truncated/overflow-padded string may come out one column short of
    w when a wide glyph straddles the truncation boundary.
  * a wrap() line may exceed w only when it holds a single glyph that is
    itself wider than w (e.g. a CJK char or emoji at w=1).

The corpus and widths are deterministic so any failure reproduces.
"""

import random
import unittest

from puretui import term

N_CASES = 300
MAX_W = 40

_ASCII = "abcdefgh ijkl MNOP 0123 .,:;!?-_/()"
_WIDE = "日本語漢字中文한글"  # CJK + Hangul
_COMBINING = "̣́̈̊"
_EMOJI = "\U0001f389⚽\U0001f525\U0001f680\U0001f3c6✨⭐"
_SGR = (
    "\x1b[0m", "\x1b[m", "\x1b[1m", "\x1b[31m", "\x1b[1;4m",
    "\x1b[38;5;196m", "\x1b[48;5;24m",
    "\x1b[38;2;10;200;30m", "\x1b[48;2;5;6;7m\x1b[1m",
)
_ALIGNS = ("left", "right", "center")


def _gen_string(rnd):
    parts = []
    for _ in range(rnd.randint(0, 14)):
        k = rnd.random()
        if k < 0.35:
            parts.append("".join(rnd.choice(_ASCII)
                                 for _ in range(rnd.randint(1, 6))))
        elif k < 0.55:
            parts.append(rnd.choice(_WIDE))
        elif k < 0.70:
            parts.append(rnd.choice(_EMOJI))
        elif k < 0.80:
            parts.append(rnd.choice(_COMBINING))
        elif k < 0.90:
            parts.append(rnd.choice(_SGR))
        else:
            parts.append(" " * rnd.randint(1, 3))
    return "".join(parts)


_RND = random.Random(0xF00D)
CORPUS = [_gen_string(_RND) for _ in range(N_CASES)]
# One random width per case for the invariants that don't sweep 0..40.
WIDTHS = [_RND.randint(0, MAX_W) for _ in range(N_CASES)]


class TestTruncateWidthBound(unittest.TestCase):
    """(a) display_width(truncate(s, w)) <= w for w in 0..40."""

    def test_width_bound(self):
        dw = term.display_width
        for s in CORPUS:
            visible = dw(s)
            for w in range(MAX_W + 1):
                out = term.truncate(s, w)
                # w=0 with visible content still emits the bare ellipsis.
                bound = w if (w > 0 or visible == 0) else 1
                got = dw(out)
                self.assertLessEqual(
                    got, bound,
                    "truncate(%r, %d) -> %r is %d cols" % (s, w, out, got))


class TestPadWidth(unittest.TestCase):
    """(b) pad(s, w) fills to exactly w columns when s fits.

    When s overflows, pad() truncates instead of returning
    max(w, display_width(s)) columns; the result is then w columns, or
    w-1 when a wide glyph straddles the boundary (never more than w).
    """

    def test_pad_width(self):
        dw = term.display_width
        for i, s in enumerate(CORPUS):
            visible = dw(s)
            for w in range(MAX_W + 1):
                align = _ALIGNS[(i + w) % 3]
                out = term.pad(s, w, align)
                got = dw(out)
                if visible <= w:
                    self.assertEqual(
                        got, w,
                        "pad(%r, %d, %r) -> %r is %d cols"
                        % (s, w, align, out, got))
                elif w == 0:
                    self.assertLessEqual(got, 1)  # ellipsis floor
                else:
                    self.assertTrue(
                        w - 1 <= got <= w,
                        "pad overflow (%r, %d) -> %r is %d cols"
                        % (s, w, out, got))


class TestWrapLineWidths(unittest.TestCase):
    """(c) every line of wrap(s, w) is at most w columns wide.

    Exemption: a line holding a single glyph that is itself wider than w
    (wrap never splits inside a glyph).
    """

    def test_line_widths(self):
        dw = term.display_width
        cw = term.char_width
        for s in CORPUS:
            for w in range(1, MAX_W + 1):
                for line in term.wrap(s, w):
                    got = dw(line)
                    if got <= w:
                        continue
                    glyphs = [c for c in term.strip_ansi(line)
                              if cw(c) > 0]
                    self.assertTrue(
                        len(glyphs) == 1 and cw(glyphs[0]) > w,
                        "wrap(%r, %d) line %r is %d cols and is not a "
                        "single over-wide glyph" % (s, w, line, got))


class TestAnsiNeverSplit(unittest.TestCase):
    """(d) every ESC in any output starts a complete SGR sequence."""

    def _assert_intact(self, out, ctx):
        i = out.find("\x1b")
        while i != -1:
            self.assertIsNotNone(
                term._SGR_RE.match(out, i),
                "%s: dangling ESC at %d in %r" % (ctx, i, out))
            i = out.find("\x1b", i + 1)

    def test_truncate(self):
        for s, w in zip(CORPUS, WIDTHS):
            self._assert_intact(term.truncate(s, w),
                                "truncate(%r, %d)" % (s, w))

    def test_pad(self):
        for i, (s, w) in enumerate(zip(CORPUS, WIDTHS)):
            align = _ALIGNS[i % 3]
            self._assert_intact(term.pad(s, w, align),
                                "pad(%r, %d, %r)" % (s, w, align))

    def test_wrap(self):
        for s, w in zip(CORPUS, WIDTHS):
            w = max(1, w)
            for line in term.wrap(s, w):
                self._assert_intact(line, "wrap(%r, %d)" % (s, w))


class TestContentPreserved(unittest.TestCase):
    """(e) strip_ansi(output) preserves the visible character stream."""

    def _assert_prefix_with_ellipsis(self, s, out, ctx):
        """Truncated output = prefix of the input's visible chars + '…'."""
        st = term.strip_ansi(out)
        self.assertTrue(st.endswith("…"),
                        "%s: %r lacks ellipsis" % (ctx, out))
        body = st[:-1]
        self.assertEqual(
            body, term.strip_ansi(s)[:len(body)],
            "%s: %r is not a prefix of the input" % (ctx, out))

    def test_truncate(self):
        for s, w in zip(CORPUS, WIDTHS):
            out = term.truncate(s, w)
            if term.display_width(s) <= w:
                self.assertEqual(out, s)
            else:
                self._assert_prefix_with_ellipsis(
                    s, out, "truncate(%r, %d)" % (s, w))

    def test_pad(self):
        for i, (s, w) in enumerate(zip(CORPUS, WIDTHS)):
            align = _ALIGNS[i % 3]
            out = term.pad(s, w, align)
            visible = term.display_width(s)
            if visible > w:
                self._assert_prefix_with_ellipsis(
                    s, out, "pad(%r, %d, %r)" % (s, w, align))
                continue
            gap = w - visible
            stripped = term.strip_ansi(s)
            if align == "left":
                expect = stripped + " " * gap
            elif align == "right":
                expect = " " * gap + stripped
            else:
                expect = " " * (gap // 2) + stripped + " " * (gap - gap // 2)
            self.assertEqual(term.strip_ansi(out), expect,
                             "pad(%r, %d, %r) -> %r" % (s, w, align, out))

    def test_wrap(self):
        for s, w in zip(CORPUS, WIDTHS):
            w = max(1, w)
            lines = term.wrap(s, w)
            joined = "".join(term.strip_ansi(ln) for ln in lines)
            self.assertEqual(
                joined.replace(" ", ""),
                term.strip_ansi(s).replace(" ", ""),
                "wrap(%r, %d) lost or reordered visible chars: %r"
                % (s, w, lines))


if __name__ == "__main__":
    unittest.main()
