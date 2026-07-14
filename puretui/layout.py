"""
layout.py - Flexbox-style layout engine for terminal cells.

`Rect` describes a rectangular region in (row, col, height, width) order,
matching Canvas arguments. `vsplit`/`hsplit` divide a Rect into children
described by `Fixed` and `Flex` specs (bare ints mean Fixed). Distribution
is fully deterministic: flex space is shared by weight with a
largest-remainder rule, min/max clamps are redistributed iteratively, and
overflow degrades to zero-size Rects rather than ever going negative.
"""

__all__ = ["Rect", "Fixed", "Flex", "vsplit", "hsplit"]


class Rect:
    """A rectangle: row, col, height, width."""

    __slots__ = ("r", "c", "h", "w")

    def __init__(self, r, c, h, w):
        self.r = r
        self.c = c
        self.h = h
        self.w = w

    @property
    def bottom(self):
        return self.r + self.h

    @property
    def right(self):
        return self.c + self.w

    def inset(self, dr, dc=None):
        """New Rect shrunk by dr rows top+bottom and dc cols left+right.

        dc defaults to dr. Size is clamped to non-negative.
        """
        if dc is None:
            dc = dr
        return Rect(self.r + dr, self.c + dc,
                    max(0, self.h - 2 * dr), max(0, self.w - 2 * dc))

    def __eq__(self, other):
        if not isinstance(other, Rect):
            return NotImplemented
        return (self.r, self.c, self.h, self.w) == (other.r, other.c, other.h, other.w)

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    def __hash__(self):
        return hash((self.r, self.c, self.h, self.w))

    def __repr__(self):
        return f"Rect(r={self.r}, c={self.c}, h={self.h}, w={self.w})"


class Fixed:
    """Exactly n cells."""

    __slots__ = ("n",)

    def __init__(self, n):
        self.n = max(0, int(n))

    def __repr__(self):
        return f"Fixed({self.n})"


class Flex:
    """Weight-proportional share of leftover space, clamped to [min, max]."""

    __slots__ = ("weight", "min", "max")

    def __init__(self, weight=1, min=0, max=None):
        self.weight = weight
        self.min = min
        self.max = max

    def __repr__(self):
        return f"Flex(weight={self.weight}, min={self.min}, max={self.max})"


def _normalize(specs):
    out = []
    for s in specs:
        if isinstance(s, int):
            out.append(Fixed(s))
        elif isinstance(s, (Fixed, Flex)):
            out.append(s)
        else:
            raise TypeError(f"bad layout spec: {s!r}")
    return out


def _share(amount, items):
    """Split `amount` cells among (index, weight) items by weight.

    Floors each share, then hands out remaining cells one each in order of
    largest fractional part, ties broken by earlier index. Returns
    {index: cells}. Deterministic.
    """
    amount = max(0, amount)
    alloc = {i: 0 for i, _ in items}
    total_w = sum(w for _, w in items if w > 0)
    if not items or total_w <= 0 or amount == 0:
        return alloc
    fracs = []
    given = 0
    for i, w in items:
        if w <= 0:
            continue
        exact = amount * w / total_w
        base = int(exact)
        alloc[i] = base
        given += base
        fracs.append((-(exact - base), i))
    fracs.sort()
    left = amount - given
    for _, i in fracs:
        if left <= 0:
            break
        alloc[i] += 1
        left -= 1
    return alloc


def _distribute(extent, specs, gap):
    """Return a size per spec for a 1-D extent. Sizes may overrun `extent`;
    the caller clips when positioning (degradation)."""
    n = len(specs)
    sizes = [0] * n
    fixed_total = 0
    flex_idx = []
    for i, s in enumerate(specs):
        if isinstance(s, Fixed):
            sizes[i] = s.n
            fixed_total += s.n
        else:
            flex_idx.append(i)
    gaps = gap * (n - 1) if n > 1 else 0
    available = max(0, extent - gaps - fixed_total)

    if flex_idx:
        frozen = {}
        for _ in range(n):
            active = [i for i in flex_idx if i not in frozen]
            if not active:
                break
            remaining = available - sum(frozen.values())
            alloc = _share(remaining, [(i, specs[i].weight) for i in active])
            clamped = {}
            violation = 0
            for i in active:
                lo = max(0, specs[i].min)
                hi = specs[i].max
                v = alloc[i]
                cv = max(lo, hi) if hi is not None and v > hi else max(v, lo)
                clamped[i] = cv
                violation += cv - v
            if violation == 0:
                frozen.update(clamped)
                break
            # Freeze only the losing side of the aggregate violation, so
            # space freed by max-clamped items can still flow to items that
            # merely dipped below their min this round (and vice versa).
            for i in active:
                if (violation > 0 and clamped[i] > alloc[i]) or \
                   (violation < 0 and clamped[i] < alloc[i]):
                    frozen[i] = clamped[i]
        for i in flex_idx:
            if i in frozen:
                sizes[i] = frozen[i]
    return sizes


def _split(rect, specs, gap, vertical):
    specs = _normalize(specs)
    if not specs:
        return []
    if gap < 0:
        gap = 0
    extent = rect.h if vertical else rect.w
    start = rect.r if vertical else rect.c
    end = start + extent
    sizes = _distribute(extent, specs, gap)
    out = []
    pos = start
    last = len(specs) - 1
    for i, size in enumerate(sizes):
        pos = min(pos, end)
        size = max(0, min(size, end - pos))
        if vertical:
            out.append(Rect(pos, rect.c, size, rect.w))
        else:
            out.append(Rect(rect.r, pos, rect.h, size))
        pos += size
        if i != last:
            pos += gap
    return out


def vsplit(rect, *specs, gap=0):
    """Split `rect` into stacked rows; each child spans the full width.

    Specs are Fixed/Flex (bare ints mean Fixed). `gap` blank rows go
    between consecutive children. Returns a list of Rects in order.
    """
    return _split(rect, specs, gap, True)


def hsplit(rect, *specs, gap=0):
    """Split `rect` into side-by-side columns; each child spans the full
    height. Same rules as vsplit."""
    return _split(rect, specs, gap, False)
