from __future__ import annotations

import unittest

import numpy as np

from core.fits_data import FITSData
from core.image_comparison import (
    ComparisonAlignment,
    ComparisonFailureCode,
    ComparisonMode,
    compare_fits_images,
)


class _LinearWCS:
    pixel_n_dim = 2
    world_n_dim = 2

    def __init__(self, *, offset_x: float = 0.0, offset_y: float = 0.0) -> None:
        self.offset_x = offset_x
        self.offset_y = offset_y

    def pixel_to_world_values(self, x, y):
        return np.asarray(x) + self.offset_x, np.asarray(y) + self.offset_y

    def world_to_pixel_values(self, x, y):
        return np.asarray(x) - self.offset_x, np.asarray(y) - self.offset_y


class _UnreliableWCS(_LinearWCS):
    def world_to_pixel_values(self, x, y):
        return np.asarray(x), np.asarray(y)


class _FailingWCS(_LinearWCS):
    def world_to_pixel_values(self, x, y):
        raise RuntimeError("synthetic transform failure")


class _NonFiniteRoundtripWCS(_LinearWCS):
    def pixel_to_world_values(self, x, y):
        shape = np.broadcast(np.asarray(x), np.asarray(y)).shape
        return np.full(shape, np.nan), np.full(shape, np.nan)


def _fits(data: np.ndarray, wcs=None) -> FITSData:
    return FITSData(data=data, wcs=wcs, has_wcs=wcs is not None)


class TestImageComparison(unittest.TestCase):
    def test_equal_shape_side_by_side_reuses_inputs_and_counts_finite_overlap(self) -> None:
        left = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float64)
        right = np.array([[1.5, 2.0], [np.inf, 4.5]], dtype=np.float64)

        result = compare_fits_images(left, right, mode="side-by-side")

        self.assertTrue(result.success)
        self.assertEqual(result.mode, ComparisonMode.SIDE_BY_SIDE)
        self.assertEqual(result.alignment_used, ComparisonAlignment.PIXEL)
        self.assertIs(result.left_image, left)
        self.assertIs(result.right_image, right)
        self.assertIsNone(result.difference_image)
        self.assertEqual(result.finite_overlap_pixels, 2)
        self.assertEqual(result.invalid_overlap_pixels, 2)

    def test_direct_difference_is_left_minus_right_and_masks_nonfinite_pixels(self) -> None:
        left = np.array([[5.0, np.nan], [9.0, np.inf]], dtype=np.float64)
        right = np.array([[2.0, 1.0], [4.0, 7.0]], dtype=np.float64)

        result = compare_fits_images(left, right, mode=ComparisonMode.DIFFERENCE)

        self.assertTrue(result.success)
        self.assertEqual(result.difference_image.dtype, np.dtype(np.float32))
        self.assertEqual(float(result.difference_image[0, 0]), 3.0)
        self.assertEqual(float(result.difference_image[1, 0]), 5.0)
        self.assertTrue(np.isnan(result.difference_image[0, 1]))
        self.assertTrue(np.isnan(result.difference_image[1, 1]))
        self.assertEqual(result.finite_overlap_pixels, 2)

    def test_difference_overflow_is_masked_instead_of_reported_as_finite(self) -> None:
        maximum = np.finfo(np.float64).max

        result = compare_fits_images(
            np.asarray([[maximum]]),
            np.asarray([[-maximum]]),
            mode="difference",
        )

        self.assertTrue(result.success)
        self.assertTrue(np.isnan(result.difference_image[0, 0]))
        self.assertEqual(result.finite_overlap_pixels, 0)
        self.assertEqual(result.invalid_overlap_pixels, 1)
        self.assertIsNotNone(result.warning)

    def test_float64_difference_can_be_requested_explicitly(self) -> None:
        left = np.array([[2**40]], dtype=np.int64)
        right = np.array([[1]], dtype=np.int64)

        result = compare_fits_images(
            left,
            right,
            mode="difference",
            output_dtype=np.float64,
            max_working_bytes=1_024,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.difference_image.dtype, np.dtype(np.float64))
        self.assertEqual(result.difference_image[0, 0], float(2**40 - 1))

    def test_pixel_alignment_rejects_different_shapes_with_actionable_reason(self) -> None:
        result = compare_fits_images(
            np.zeros((2, 2)),
            np.zeros((3, 2)),
            alignment="pixel",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.SHAPE_MISMATCH)
        self.assertIn("equal shapes", result.reason)
        self.assertIn("WCS", result.reason)

    def test_auto_alignment_reports_missing_wcs_for_different_shapes(self) -> None:
        result = compare_fits_images(np.zeros((2, 2)), np.zeros((2, 3)))

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.MISSING_WCS)
        self.assertIn("left image has no usable WCS", result.reason)

    def test_wcs_alignment_resamples_right_image_onto_left_grid(self) -> None:
        left_values = np.array([[10.0, 20.0, 30.0], [40.0, np.nan, 60.0]])
        right_values = np.array([
            [999.0, 10.0, 20.0, 30.0],
            [999.0, 40.0, 50.0, 60.0],
        ])
        left = _fits(left_values, _LinearWCS())
        right = _fits(right_values, _LinearWCS(offset_x=-1.0))

        side = compare_fits_images(left, right, mode="blink", alignment="auto")
        difference = compare_fits_images(left, right, mode="difference", alignment="wcs")

        self.assertTrue(side.success)
        self.assertEqual(side.alignment_used, ComparisonAlignment.WCS)
        self.assertIs(side.left_image, left_values)
        self.assertTrue(np.array_equal(side.right_image, right_values[:, 1:], equal_nan=True))
        self.assertTrue(difference.success)
        self.assertTrue(np.allclose(
            difference.difference_image[[0, 0, 0, 1, 1], [0, 1, 2, 0, 2]],
            0.0,
        ))
        self.assertTrue(np.isnan(difference.difference_image[1, 1]))
        self.assertEqual(difference.finite_overlap_pixels, 5)

    def test_wcs_alignment_returns_clear_no_overlap_reason(self) -> None:
        left = _fits(np.ones((2, 2)), _LinearWCS())
        right = _fits(np.ones((2, 2)), _LinearWCS(offset_x=100.0))

        result = compare_fits_images(left, right, alignment="wcs")

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.NO_OVERLAP)
        self.assertIn("do not overlap", result.reason)

    def test_wcs_roundtrip_guard_rejects_inconsistent_transform(self) -> None:
        left = _fits(np.ones((3, 3)), _LinearWCS())
        right = _fits(np.ones((3, 3)), _UnreliableWCS(offset_x=10.0))

        result = compare_fits_images(left, right, alignment="wcs")

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.WCS_UNRELIABLE)
        self.assertIn("round-trip residual", result.reason)

    def test_wcs_transform_exception_is_returned_instead_of_escaping(self) -> None:
        left = _fits(np.ones((2, 2)), _LinearWCS())
        right = _fits(np.ones((2, 2)), _FailingWCS())

        result = compare_fits_images(left, right, alignment="wcs")

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.WCS_TRANSFORM_FAILED)
        self.assertIn("synthetic transform failure", result.reason)

    def test_wcs_nonfinite_roundtrip_is_reported_as_unreliable(self) -> None:
        left = _fits(np.ones((2, 2)), _LinearWCS())
        right = _fits(np.ones((2, 2)), _NonFiniteRoundtripWCS())

        result = compare_fits_images(left, right, alignment="wcs")

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.WCS_UNRELIABLE)
        self.assertIn("non-finite", result.reason)

    def test_wcs_alignment_has_a_separate_pixel_budget(self) -> None:
        left = _fits(np.ones((3, 3)), _LinearWCS())
        right = _fits(np.ones((3, 3)), _LinearWCS())

        result = compare_fits_images(left, right, alignment="wcs", max_wcs_pixels=8)

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.OUTPUT_LIMIT)
        self.assertIn("9 pixels", result.reason)

    def test_difference_rejects_memory_budget_before_allocating_output(self) -> None:
        result = compare_fits_images(
            np.ones((10, 10)),
            np.ones((10, 10)),
            mode="difference",
            max_working_bytes=500,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, ComparisonFailureCode.MEMORY_LIMIT)
        self.assertIn("working row", result.reason)

    def test_non_2d_and_complex_inputs_are_rejected(self) -> None:
        dimensional = compare_fits_images(np.ones(3), np.ones(3))
        complex_result = compare_fits_images(
            np.ones((2, 2), dtype=np.complex64),
            np.ones((2, 2)),
        )

        self.assertEqual(dimensional.reason_code, ComparisonFailureCode.INVALID_DIMENSIONS)
        self.assertEqual(complex_result.reason_code, ComparisonFailureCode.UNSUPPORTED_DTYPE)

    def test_invalid_options_and_output_pixel_budget_have_stable_codes(self) -> None:
        invalid_mode = compare_fits_images(np.ones((1, 1)), np.ones((1, 1)), mode="wipe")
        invalid_dtype = compare_fits_images(
            np.ones((1, 1)),
            np.ones((1, 1)),
            output_dtype="not-a-dtype",
        )
        too_many_pixels = compare_fits_images(
            np.ones((2, 2)),
            np.ones((2, 2)),
            max_output_pixels=3,
        )

        self.assertEqual(invalid_mode.reason_code, ComparisonFailureCode.INVALID_OPTION)
        self.assertEqual(invalid_dtype.reason_code, ComparisonFailureCode.INVALID_OPTION)
        self.assertEqual(too_many_pixels.reason_code, ComparisonFailureCode.OUTPUT_LIMIT)


if __name__ == "__main__":
    unittest.main()
