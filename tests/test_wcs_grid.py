from __future__ import annotations

import math
import unittest

from astropy.wcs import WCS

from astroview.core.wcs_grid import (
    MAX_GRID_LINES_PER_AXIS,
    MAX_GRID_SAMPLES_PER_LINE,
    build_wcs_grid,
)


def _simple_wcs() -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [50.5, 40.5]
    wcs.wcs.cdelt = [-0.01, 0.01]
    wcs.wcs.crval = [180.0, 30.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


class TestWCSGrid(unittest.TestCase):
    def test_builds_visible_ra_and_dec_segments(self) -> None:
        grid = build_wcs_grid(_simple_wcs(), 100, 80)

        self.assertAlmostEqual(grid.center_ra_deg, 180.0, places=2)
        self.assertAlmostEqual(grid.center_dec_deg, 30.0, places=2)
        self.assertGreater(grid.field_radius_deg, 0.0)
        self.assertTrue(any(line.axis == "ra" for line in grid.lines))
        self.assertTrue(any(line.axis == "dec" for line in grid.lines))
        for line in grid.lines:
            self.assertTrue(line.label)
            self.assertTrue(line.segments)
            for segment in line.segments:
                self.assertGreaterEqual(len(segment), 2)
                self.assertTrue(all(math.isfinite(x) and math.isfinite(y) for x, y in segment))

    def test_hard_caps_line_and_sample_counts(self) -> None:
        grid = build_wcs_grid(
            _simple_wcs(),
            100,
            80,
            target_lines=10_000,
            samples_per_line=10_000,
        )
        self.assertLessEqual(len(grid.lines), MAX_GRID_LINES_PER_AXIS * 2)
        for line in grid.lines:
            self.assertLessEqual(sum(len(segment) for segment in line.segments), MAX_GRID_SAMPLES_PER_LINE)

    def test_rejects_tiny_image_and_invalid_wcs(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 2 by 2"):
            build_wcs_grid(_simple_wcs(), 1, 50)
        with self.assertRaises(Exception):
            build_wcs_grid(object(), 100, 100)


if __name__ == "__main__":
    unittest.main()
