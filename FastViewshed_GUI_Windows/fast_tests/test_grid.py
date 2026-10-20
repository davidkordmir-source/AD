"""Regressions for the reported 5725-square grid and explicit detail choices."""

import math
import unittest

from fast_viewshed.engine import grid_plan
from fast_viewshed.model import FastSettings


class GridPlanTests(unittest.TestCase):
    def test_reported_5725_grid_fits_default_without_changing_radius(self):
        messages = []
        radius = 28590
        cell, n, size = grid_plan(radius, 10, 25_000_000, True, 0, messages.append)
        self.assertEqual(size, 4999)
        self.assertLessEqual(size*size, 25_000_000)
        self.assertGreaterEqual((n-3)*cell, radius)
        self.assertGreater(cell, 10)
        self.assertLess(cell, 12)
        self.assertIn("5725×5725", messages[0])
        self.assertIn("کاهش جزئیات", messages[0])

    def test_reported_grid_keeps_original_pixels_when_limit_is_40_million(self):
        self.assertEqual(grid_plan(28590, 10, 40_000_000, False, 0, self.fail), (10, 2862, 5725))

    def test_strict_mode_explains_size_and_required_pixel(self):
        with self.assertRaisesRegex(ValueError, "5725×5725.*حداقل.*متر"):
            grid_plan(28590, 10, 25_000_000, False, 7, self.fail)

    def test_small_grid_is_unchanged(self):
        self.assertEqual(grid_plan(700, 10, 25_000_000, True, 0, self.fail), (10, 73, 147))

    def test_rounding_never_exceeds_selected_limit(self):
        for cells in (1_000_000, 25_000_000, 40_000_000, 100_000_000):
            for radius in (1.23456789, 700, 28590, 300000):
                with self.subTest(cells=cells, radius=radius):
                    cell, n, size = grid_plan(radius, radius/6000, cells, True, 0, lambda _: None)
                    self.assertLessEqual(size*size, cells)
                    self.assertEqual(n, math.ceil(radius/cell)+3)
                    self.assertEqual(size, 2*n+1)

    def test_grid_limit_validation(self):
        for limit in (0, 101, 2.5, True):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "سقف شبکه"):
                FastSettings("p", "d", "s", "e", "o", max_grid_mcells=limit).validate()


if __name__ == "__main__":
    unittest.main()
