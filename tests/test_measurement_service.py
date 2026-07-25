from __future__ import annotations

from dataclasses import fields
import math
import unittest

import numpy as np

from core.contracts import ROISelection
from core.measurement_service import MeasurementService


class TestMeasurementService(unittest.TestCase):
    def test_roi_statistics_follow_xy_slice_convention_and_ignore_non_finite_pixels(self) -> None:
        data = np.array(
            [
                [1.0, np.nan, 3.0],
                [4.0, np.inf, 6.0],
                [7.0, 8.0, 9.0],
            ]
        )

        result = MeasurementService().measure_roi(
            data,
            ROISelection(x0=1, y0=0, width=2, height=3),
        )

        self.assertEqual(result.roi, ROISelection(x0=1, y0=0, width=2, height=3))
        self.assertEqual(result.pixel_count, 6)
        self.assertEqual(result.finite_pixel_count, 4)
        self.assertEqual(result.invalid_pixel_count, 2)
        self.assertEqual(result.minimum, 3.0)
        self.assertEqual(result.maximum, 9.0)
        self.assertAlmostEqual(result.mean, 6.5)
        self.assertAlmostEqual(result.median, 7.0)
        self.assertAlmostEqual(result.standard_deviation, float(np.std([3.0, 6.0, 8.0, 9.0])))
        self.assertAlmostEqual(result.sum_value, 26.0)

    def test_roi_is_clipped_like_sep_and_budget_is_checked_after_clipping(self) -> None:
        data = np.arange(16, dtype=np.float32).reshape(4, 4)
        roi = ROISelection(x0=-1, y0=-1, width=3, height=3)

        result = MeasurementService(max_sample_pixels=4).measure_roi(data, roi)

        self.assertEqual(result.roi, ROISelection(x0=0, y0=0, width=2, height=2))
        self.assertEqual(result.sum_value, 10.0)
        with self.assertRaisesRegex(ValueError, r"4 sampled pixels"):
            MeasurementService(max_sample_pixels=3).measure_roi(data, roi)

    def test_all_invalid_roi_returns_counts_without_nan_results(self) -> None:
        data = np.array([[np.nan, np.inf], [-np.inf, np.nan]])

        result = MeasurementService().measure_roi(
            data,
            ROISelection(x0=0, y0=0, width=2, height=2),
        )

        self.assertEqual(result.finite_pixel_count, 0)
        self.assertEqual(result.invalid_pixel_count, 4)
        for name in (
            "minimum",
            "maximum",
            "mean",
            "median",
            "standard_deviation",
            "sum_value",
        ):
            self.assertIsNone(getattr(result, name))

    def test_roi_validation_rejects_invalid_shapes_types_and_empty_selections(self) -> None:
        service = MeasurementService()
        with self.assertRaisesRegex(ValueError, r"2D image"):
            service.measure_roi(
                np.zeros((2, 2, 2)),
                ROISelection(x0=0, y0=0, width=1, height=1),
            )
        with self.assertRaisesRegex(ValueError, r"real numeric"):
            service.measure_roi(
                np.array([[1 + 2j]]),
                ROISelection(x0=0, y0=0, width=1, height=1),
            )
        with self.assertRaisesRegex(ValueError, r"width and height must be positive"):
            service.measure_roi(
                np.zeros((2, 2)),
                ROISelection(x0=0, y0=0, width=0, height=1),
            )
        with self.assertRaisesRegex(ValueError, r"empty after clipping"):
            service.measure_roi(
                np.zeros((2, 2)),
                ROISelection(x0=5, y0=5, width=1, height=1),
            )

    def test_roi_overflow_is_reported_as_unavailable_instead_of_infinity(self) -> None:
        result = MeasurementService().measure_roi(
            np.full((2, 2), 1.0e308),
            ROISelection(x0=0, y0=0, width=2, height=2),
        )

        self.assertIsNone(result.sum_value)
        self.assertTrue(math.isfinite(result.mean))
        self.assertTrue(math.isfinite(result.standard_deviation))

    def test_aperture_photometry_recovers_gaussian_centroid_fwhm_flux_and_snr(self) -> None:
        height = width = 101
        yy, xx = np.mgrid[:height, :width]
        center_x = 50.25
        center_y = 49.75
        sigma = 2.0
        signal = 1000.0 * np.exp(
            -((xx - center_x) ** 2 + (yy - center_y) ** 2) / (2.0 * sigma * sigma)
        )
        checker_noise = np.where((xx + yy) % 2 == 0, -1.0, 1.0)
        data = 100.0 + checker_noise + signal

        result = MeasurementService().measure_aperture(
            data,
            center_x=center_x,
            center_y=center_y,
            aperture_radius=8.0,
            background_inner_radius=12.0,
            background_outer_radius=18.0,
        )

        aperture_mask = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= 8.0**2
        expected_flux = float(np.sum(data[aperture_mask] - result.background_per_pixel))
        self.assertAlmostEqual(result.net_flux, expected_flux, places=8)
        self.assertAlmostEqual(result.centroid_x, center_x, delta=0.04)
        self.assertAlmostEqual(result.centroid_y, center_y, delta=0.04)
        self.assertAlmostEqual(result.fwhm, 2.354820045 * sigma, delta=0.12)
        self.assertGreater(result.background_rms, 0.0)
        expected_uncertainty = result.background_rms * math.sqrt(
            result.aperture_finite_pixel_count
            + result.aperture_finite_pixel_count**2 / result.background_finite_pixel_count
        )
        self.assertAlmostEqual(result.flux_uncertainty, expected_uncertainty)
        self.assertAlmostEqual(result.snr, result.net_flux / expected_uncertainty)

    def test_aperture_ignores_invalid_pixels_and_never_returns_nan_or_infinity(self) -> None:
        yy, xx = np.mgrid[:31, :31]
        data = 10.0 + 50.0 * np.exp(-((xx - 15.0) ** 2 + (yy - 15.0) ** 2) / 4.0)
        data[15, 15] = np.nan
        data[15, 24] = np.inf

        result = MeasurementService().measure_aperture(
            data,
            center_x=15.0,
            center_y=15.0,
            aperture_radius=5.0,
            background_inner_radius=8.0,
            background_outer_radius=11.0,
        )

        self.assertGreaterEqual(result.invalid_pixel_count, 2)
        for field in fields(result):
            value = getattr(result, field.name)
            if isinstance(value, float):
                self.assertTrue(math.isfinite(value), field.name)

    def test_constant_aperture_has_zero_flux_and_undefined_shape_and_snr(self) -> None:
        result = MeasurementService().measure_aperture(
            np.full((31, 31), 7.5),
            center_x=15.0,
            center_y=15.0,
            aperture_radius=4.0,
            background_inner_radius=7.0,
            background_outer_radius=10.0,
        )

        self.assertAlmostEqual(result.net_flux, 0.0)
        self.assertAlmostEqual(result.background_per_pixel, 7.5)
        self.assertAlmostEqual(result.background_rms, 0.0)
        self.assertEqual(result.flux_uncertainty, 0.0)
        self.assertIsNone(result.snr)
        self.assertIsNone(result.centroid_x)
        self.assertIsNone(result.centroid_y)
        self.assertIsNone(result.fwhm)

    def test_aperture_enforces_radii_bounds_background_samples_and_resource_budget(self) -> None:
        data = np.ones((100, 100), dtype=np.float32)
        service = MeasurementService(max_sample_pixels=100)
        with self.assertRaisesRegex(ValueError, r"Radii must satisfy"):
            service.measure_aperture(
                data,
                center_x=50,
                center_y=50,
                aperture_radius=5,
                background_inner_radius=4,
                background_outer_radius=8,
            )
        with self.assertRaisesRegex(ValueError, r"outside the image"):
            service.measure_aperture(
                data,
                center_x=-1,
                center_y=50,
                aperture_radius=2,
                background_inner_radius=3,
                background_outer_radius=4,
            )
        with self.assertRaisesRegex(ValueError, r"measurement safety limit"):
            service.measure_aperture(
                data,
                center_x=50,
                center_y=50,
                aperture_radius=2,
                background_inner_radius=5,
                background_outer_radius=10,
            )

        sparse = np.full((21, 21), np.nan)
        sparse[10, 10] = 1.0
        with self.assertRaisesRegex(ValueError, r"Background annulus contains only 0"):
            MeasurementService().measure_aperture(
                sparse,
                center_x=10,
                center_y=10,
                aperture_radius=2,
                background_inner_radius=4,
                background_outer_radius=6,
            )

    def test_aperture_rejects_non_finite_boolean_and_empty_image_inputs(self) -> None:
        service = MeasurementService()
        data = np.ones((15, 15), dtype=np.float64)
        valid = {
            "center_x": 7.0,
            "center_y": 7.0,
            "aperture_radius": 2.0,
            "background_inner_radius": 3.0,
            "background_outer_radius": 5.0,
        }

        for field_name, invalid_value in (
            ("center_x", np.nan),
            ("center_y", np.inf),
            ("aperture_radius", 0.0),
            ("background_inner_radius", True),
            ("background_outer_radius", np.bool_(True)),
        ):
            with self.subTest(field=field_name, value=invalid_value):
                parameters = dict(valid)
                parameters[field_name] = invalid_value
                with self.assertRaisesRegex(ValueError, r"finite number|positive"):
                    service.measure_aperture(data, **parameters)

        with self.assertRaisesRegex(ValueError, r"image is empty"):
            service.measure_aperture(np.empty((0, 0)), **valid)

    def test_aperture_at_image_edge_uses_only_sampled_pixels(self) -> None:
        data = np.full((25, 25), 10.0)
        data[0, 0] = 50.0

        result = MeasurementService(min_background_pixels=3).measure_aperture(
            data,
            center_x=0.0,
            center_y=0.0,
            aperture_radius=1.5,
            background_inner_radius=2.0,
            background_outer_radius=4.0,
        )

        self.assertEqual(result.aperture_pixel_count, 4)
        self.assertEqual(result.aperture_finite_pixel_count, 4)
        self.assertEqual(result.invalid_pixel_count, 0)
        self.assertAlmostEqual(result.background_per_pixel, 10.0)
        self.assertAlmostEqual(result.background_total, 40.0)
        self.assertAlmostEqual(result.net_flux, 40.0)
        self.assertAlmostEqual(result.centroid_x, 0.0)
        self.assertAlmostEqual(result.centroid_y, 0.0)

    def test_roi_rejects_numpy_boolean_coordinates(self) -> None:
        with self.assertRaisesRegex(ValueError, r"roi.x0 must be an integer"):
            MeasurementService().measure_roi(
                np.ones((2, 2)),
                ROISelection(x0=np.bool_(True), y0=0, width=1, height=1),
            )

    def test_service_resource_configuration_rejects_boolean_and_non_positive_values(self) -> None:
        for value in (True, np.bool_(True), 0, -1, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, r"positive integer"):
                    MeasurementService(max_sample_pixels=value)

        for value in (False, np.bool_(False), 0, -1, 1.5):
            with self.subTest(min_background_pixels=value):
                with self.assertRaisesRegex(ValueError, r"positive integer"):
                    MeasurementService(min_background_pixels=value)


if __name__ == "__main__":
    unittest.main()
