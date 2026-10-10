from __future__ import annotations

import itertools
import unittest

import numpy as np

from astroview.core.image_geometry import (
    axis_directions, display_dimensions, orient_edge_point, orient_point,
    unorient_edge_point, unorient_point,
)


ORIENTATIONS = tuple(itertools.product((False, True), repeat=3))


def oriented(array, orientation):
    horizontal, vertical, transpose = orientation
    result = array.T if transpose else array
    if horizontal:
        result = result[:, ::-1]
    if vertical:
        result = result[::-1, :]
    return result


class TestImageGeometry(unittest.TestCase):
    def test_pixel_centers_match_array_operations_for_every_orientation(self):
        original = np.arange(35).reshape(5, 7)
        for orientation in ORIENTATIONS:
            with self.subTest(orientation=orientation):
                displayed = oriented(original, orientation)
                self.assertEqual(display_dimensions(7, 5, orientation), displayed.shape[::-1])
                for y in range(5):
                    for x in range(7):
                        dx, dy = orient_point(x, y, 7, 5, orientation)
                        self.assertEqual(displayed[dy, dx], original[y, x])
                        self.assertEqual(unorient_point(dx, dy, 7, 5, orientation), (x, y))

    def test_fractional_coordinates_round_trip_without_integer_rounding(self):
        for orientation in ORIENTATIONS:
            for width, height in ((7, 5), (1, 9), (11, 1)):
                for point in ((0.25, 0.75), (width - 1.3, height - 1.8), (-0.5, 10.2)):
                    with self.subTest(orientation=orientation, size=(width, height), point=point):
                        displayed = orient_point(*point, width, height, orientation)
                        actual = unorient_point(*displayed, width, height, orientation)
                        np.testing.assert_allclose(actual, point, rtol=0, atol=1e-12)

    def test_half_open_selection_has_exact_same_pixels_after_orientation(self):
        original = np.zeros((5, 7), dtype=bool)
        original[1:4, 2:6] = True
        for orientation in ORIENTATIONS:
            with self.subTest(orientation=orientation):
                corners = [orient_edge_point(x, y, 7, 5, orientation) for x, y in ((2, 1), (6, 4))]
                x0, x1 = sorted(point[0] for point in corners)
                y0, y1 = sorted(point[1] for point in corners)
                actual = np.zeros(oriented(original, orientation).shape, dtype=bool)
                actual[y0:y1, x0:x1] = True
                np.testing.assert_array_equal(actual, oriented(original, orientation))
                for point, expected in zip(corners, ((2, 1), (6, 4))):
                    self.assertEqual(unorient_edge_point(*point, 7, 5, orientation), expected)

    def test_axis_vectors_match_pixel_displacements(self):
        for orientation in ORIENTATIONS:
            origin = orient_point(2.0, 3.0, 7, 5, orientation)
            positive_x = orient_point(3.0, 3.0, 7, 5, orientation)
            positive_y = orient_point(2.0, 4.0, 7, 5, orientation)
            x_axis, y_axis = axis_directions(orientation)
            self.assertEqual(x_axis, tuple(x - o for x, o in zip(positive_x, origin)))
            self.assertEqual(y_axis, tuple(y - o for y, o in zip(positive_y, origin)))


if __name__ == '__main__':
    unittest.main()
