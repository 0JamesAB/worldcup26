"""Layout engine arithmetic: Rect, Fixed/Flex, vsplit/hsplit."""

import unittest

from tui.layout import Rect, Fixed, Flex, vsplit, hsplit


class TestRect(unittest.TestCase):
    def test_edges(self):
        r = Rect(2, 3, 4, 5)
        self.assertEqual(r.bottom, 6)
        self.assertEqual(r.right, 8)

    def test_eq_and_repr(self):
        self.assertEqual(Rect(1, 2, 3, 4), Rect(1, 2, 3, 4))
        self.assertNotEqual(Rect(1, 2, 3, 4), Rect(1, 2, 3, 5))
        self.assertNotEqual(Rect(0, 0, 1, 1), "not a rect")
        self.assertIn("Rect", repr(Rect(1, 2, 3, 4)))

    def test_inset(self):
        r = Rect(0, 0, 10, 20).inset(1)
        self.assertEqual(r, Rect(1, 1, 8, 18))
        r = Rect(0, 0, 10, 20).inset(1, 3)
        self.assertEqual(r, Rect(1, 3, 8, 14))

    def test_inset_clamps_to_zero(self):
        r = Rect(0, 0, 3, 3).inset(2)
        self.assertEqual(r.h, 0)
        self.assertEqual(r.w, 0)
        r = Rect(5, 5, 1, 10).inset(1, 0)
        self.assertEqual((r.h, r.w), (0, 10))


class TestFlexDistribution(unittest.TestCase):
    def test_equal_flex_remainder_deterministic(self):
        # 10 rows / 3 equal flexes -> 4,3,3 (extra cell to earliest index).
        rects = vsplit(Rect(0, 0, 10, 20), Flex(1), Flex(1), Flex(1))
        self.assertEqual([r.h for r in rects], [4, 3, 3])
        self.assertEqual([r.r for r in rects], [0, 4, 7])
        for r in rects:
            self.assertEqual((r.c, r.w), (0, 20))

    def test_weight_proportional(self):
        rects = vsplit(Rect(0, 0, 10, 5), Flex(3), Flex(1))
        # exact 7.5/2.5, tie on fraction -> earlier index gets the cell
        self.assertEqual([r.h for r in rects], [8, 2])

    def test_repeat_is_stable(self):
        a = vsplit(Rect(0, 0, 11, 4), Flex(1), Flex(1), Flex(1), Flex(1))
        b = vsplit(Rect(0, 0, 11, 4), Flex(1), Flex(1), Flex(1), Flex(1))
        self.assertEqual(a, b)
        self.assertEqual([r.h for r in a], [3, 3, 3, 2])

    def test_fixed_flex_mix(self):
        rects = vsplit(Rect(0, 0, 20, 8), Fixed(3), Flex(1), Flex(2), Fixed(2))
        self.assertEqual([r.h for r in rects], [3, 5, 10, 2])
        self.assertEqual([r.r for r in rects], [0, 3, 8, 18])
        self.assertEqual(rects[-1].bottom, 20)

    def test_ints_are_fixed(self):
        rects = vsplit(Rect(0, 0, 10, 8), 2, Flex(1), 3)
        self.assertEqual([r.h for r in rects], [2, 5, 3])

    def test_single_flex_takes_all(self):
        rects = vsplit(Rect(2, 1, 7, 9), Flex())
        self.assertEqual(rects, [Rect(2, 1, 7, 9)])

    def test_zero_weight_gets_nothing(self):
        rects = vsplit(Rect(0, 0, 10, 4), Flex(0), Flex(1))
        self.assertEqual([r.h for r in rects], [0, 10])


class TestGaps(unittest.TestCase):
    def test_gap_accounting(self):
        rects = vsplit(Rect(0, 0, 10, 4), Flex(1), Flex(1), Flex(1), gap=1)
        # available = 10 - 2 gaps = 8 -> 3,3,2
        self.assertEqual([r.h for r in rects], [3, 3, 2])
        self.assertEqual([r.r for r in rects], [0, 4, 8])
        self.assertEqual(rects[-1].bottom, 10)

    def test_gap_with_fixed(self):
        rects = vsplit(Rect(5, 0, 12, 4), Fixed(2), Flex(1), gap=2)
        self.assertEqual([r.h for r in rects], [2, 8])
        self.assertEqual([r.r for r in rects], [5, 9])

    def test_no_trailing_gap(self):
        rects = hsplit(Rect(0, 0, 1, 9), Fixed(4), Fixed(4), gap=1)
        self.assertEqual(rects[1].right, 9)


class TestClamping(unittest.TestCase):
    def test_max_redistributes_surplus(self):
        rects = vsplit(Rect(0, 0, 10, 4), Flex(1, max=2), Flex(1))
        self.assertEqual([r.h for r in rects], [2, 8])

    def test_min_redistributes_deficit(self):
        rects = vsplit(Rect(0, 0, 10, 4), Flex(1, min=6), Flex(1))
        self.assertEqual([r.h for r in rects], [6, 4])

    def test_cascading_max_clamps(self):
        rects = vsplit(Rect(0, 0, 10, 4), Flex(1, max=2), Flex(1, max=3), Flex(1))
        self.assertEqual([r.h for r in rects], [2, 3, 5])

    def test_mins_exceeding_extent_degrade(self):
        rects = vsplit(Rect(0, 0, 4, 4), Flex(1, min=3), Flex(1, min=3), Flex(1, min=3))
        self.assertEqual([r.h for r in rects], [3, 1, 0])
        self.assertEqual(rects[-1].bottom, 4)

    def test_all_maxed_leaves_slack(self):
        rects = vsplit(Rect(0, 0, 10, 4), Flex(1, max=2), Flex(1, max=2))
        self.assertEqual([r.h for r in rects], [2, 2])

    def test_min_item_absorbs_space_freed_by_max_sibling(self):
        # The low-weight item dips below its min in round 1, but the space
        # the max-clamped sibling gives back must flow to it, not freeze
        # it at its min and underfill the extent.
        rects = hsplit(Rect(0, 0, 1, 20), Flex(1, min=10), Flex(100, max=5))
        self.assertEqual([r.w for r in rects], [15, 5])

    def test_max_freed_space_fills_extent_three_items(self):
        rects = hsplit(Rect(0, 0, 1, 30),
                       Flex(1, min=10), Flex(100, max=4), Flex(100, max=4))
        self.assertEqual([r.w for r in rects], [22, 4, 4])


class TestOverflow(unittest.TestCase):
    def test_fixed_overflow_zero_sizes_in_order(self):
        rects = vsplit(Rect(0, 0, 3, 4), Fixed(2), Fixed(2), Fixed(2))
        self.assertEqual([r.h for r in rects], [2, 1, 0])
        for r in rects:
            self.assertGreaterEqual(r.h, 0)
            self.assertLessEqual(r.bottom, 3)

    def test_tiny_rect_many_children_with_gap(self):
        parent = Rect(0, 0, 2, 3)
        rects = vsplit(parent, 2, 2, 2, 2, 2, gap=1)
        self.assertEqual(len(rects), 5)
        for r in rects:
            self.assertGreaterEqual(r.h, 0)
            self.assertGreaterEqual(r.r, parent.r)
            self.assertLessEqual(r.bottom, parent.bottom)

    def test_zero_extent(self):
        rects = hsplit(Rect(0, 0, 5, 0), Flex(1), Fixed(3))
        self.assertEqual([r.w for r in rects], [0, 0])

    def test_no_specs(self):
        self.assertEqual(vsplit(Rect(0, 0, 5, 5)), [])


class TestSymmetryAndNesting(unittest.TestCase):
    def test_hsplit_vsplit_symmetry(self):
        specs = lambda: (Fixed(3), Flex(1), Flex(2, max=8), 2)
        v = vsplit(Rect(0, 0, 24, 7), *specs(), gap=1)
        h = hsplit(Rect(0, 0, 7, 24), *specs(), gap=1)
        self.assertEqual([r.h for r in v], [r.w for r in h])
        self.assertEqual([r.r for r in v], [r.c for r in h])
        for r in h:
            self.assertEqual((r.r, r.h), (0, 7))

    def test_hsplit_children_span_full_height(self):
        rects = hsplit(Rect(2, 3, 6, 10), Flex(1), Flex(1))
        self.assertEqual(rects[0], Rect(2, 3, 6, 5))
        self.assertEqual(rects[1], Rect(2, 8, 6, 5))

    def test_nested_splits_absolute(self):
        root = Rect(1, 2, 20, 40)
        top, body = vsplit(root, Fixed(3), Flex(1))
        self.assertEqual(top, Rect(1, 2, 3, 40))
        self.assertEqual(body, Rect(4, 2, 17, 40))
        left, right = hsplit(body, Flex(1), Flex(1), gap=2)
        self.assertEqual(left, Rect(4, 2, 17, 19))
        self.assertEqual(right, Rect(4, 23, 17, 19))
        self.assertEqual(right.right, root.right)
        self.assertEqual(left.bottom, root.bottom)

    def test_nested_inset_composes(self):
        root = Rect(0, 0, 10, 10)
        _, body = vsplit(root, 2, Flex(1))
        inner = body.inset(1)
        self.assertEqual(inner, Rect(3, 1, 6, 8))


if __name__ == "__main__":
    unittest.main()
