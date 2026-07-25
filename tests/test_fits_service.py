from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from core.fits_data import FITSData
from core.fits_service import FITSService, _OriginalInterval, _subsample, render_preview_u8


class _IdentityStretch:
    def __call__(self, data: np.ndarray) -> np.ndarray:
        return data


class _FixedInterval:
    def __init__(self, vmin: float, vmax: float) -> None:
        self.vmin = vmin
        self.vmax = vmax

    def get_limits(self, data: np.ndarray) -> tuple[float, float]:
        return self.vmin, self.vmax


class TestFITSService(unittest.TestCase):
    def test_list_image_hdus_rejects_disguised_gzip_before_astropy_open(self) -> None:
        service = FITSService()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "disguised-gzip.fits"
            path.write_bytes(b"\x1f\x8b\x08\x00compressed payload")

            with patch("core.fits_data._astropy_fits") as astropy_mock:
                with self.assertRaisesRegex(ValueError, r"compression is not supported safely"):
                    service.list_image_hdus(str(path))

        astropy_mock.assert_not_called()

    def test_open_file_loads_and_stores_current_data(self) -> None:
        service = FITSService()
        loaded = FITSData(path="demo.fits")

        with patch("core.fits_service.FITSData.load", return_value=loaded) as load_mock:
            result = service.open_file("demo.fits", hdu_index=2)

        self.assertIs(result, loaded)
        self.assertIs(service.current_data, loaded)
        load_mock.assert_called_once_with("demo.fits", 2)

    def test_build_render_request_reflects_selected_controls(self) -> None:
        service = FITSService()

        service.set_stretch("Asinh")
        service.set_interval("99%")
        request = service.build_render_request()

        self.assertEqual(request.stretch_name, "Asinh")
        self.assertEqual(request.interval_name, "99%")

    def test_build_render_request_includes_manual_limits(self) -> None:
        service = FITSService()

        service.set_interval("Manual")
        service.set_manual_interval_limits(1.25, 9.75)
        request = service.build_render_request()

        self.assertEqual(request.interval_name, "Manual")
        self.assertEqual(request.manual_vmin, 1.25)
        self.assertEqual(request.manual_vmax, 9.75)

    def test_available_intervals_include_original(self) -> None:
        service = FITSService()

        self.assertIn("Original", service.AVAILABLE_INTERVALS)
        self.assertIn("Manual", service.AVAILABLE_INTERVALS)

    def test_render_returns_empty_result_when_no_image_is_loaded(self) -> None:
        service = FITSService()

        result = service.render()

        self.assertIsNone(result.image_u8)
        self.assertEqual(result.width, 0)
        self.assertEqual(result.height, 0)

    def test_render_normalizes_clips_and_preserves_dimensions(self) -> None:
        service = FITSService()
        service.current_data = FITSData(
            data=np.array([[0.0, 5.0], [10.0, 15.0]], dtype=np.float32)
        )

        with patch("core.fits_service._build_interval", return_value=_FixedInterval(0.0, 10.0)):
            with patch("core.fits_service._build_stretch", return_value=_IdentityStretch()):
                result = service.render()

        expected = np.array([[0, 127], [255, 255]], dtype=np.uint8)
        self.assertEqual(result.width, 2)
        self.assertEqual(result.height, 2)
        self.assertTrue(np.array_equal(result.image_u8, expected))

    def test_header_text_and_current_wcs_proxy_active_data(self) -> None:
        service = FITSService()
        wcs = object()
        service.current_data = FITSData(header={"NAXIS": 2}, wcs=wcs, has_wcs=True)

        with patch("core.fits_data.FITSData.header_as_text", return_value="SIMPLE  = T"):
            self.assertEqual(service.header_text(), "SIMPLE  = T")

        self.assertIs(service.current_wcs(), wcs)

    def test_render_preview_u8_returns_none_for_small_images(self) -> None:
        data = FITSData(data=np.arange(16, dtype=np.float32).reshape(4, 4))

        preview = render_preview_u8(data, "Linear", "ZScale", max_dimension=8)

        self.assertIsNone(preview)

    def test_render_preview_u8_upscales_preview_back_to_full_shape(self) -> None:
        data = FITSData(data=np.arange(16, dtype=np.float32).reshape(4, 4))
        preview_tile = np.array([[10, 20], [30, 40]], dtype=np.uint8)

        with patch("core.fits_service.render_image_u8", return_value=preview_tile) as render_mock:
            preview = render_preview_u8(data, "Linear", "ZScale", max_dimension=2)

        self.assertEqual(preview.shape, (4, 4))
        self.assertTrue(np.array_equal(
            preview,
            np.array(
                [[10, 10, 20, 20], [10, 10, 20, 20], [30, 30, 40, 40], [30, 30, 40, 40]],
                dtype=np.uint8,
            ),
        ))
        render_data = render_mock.call_args.args[0]
        self.assertEqual(render_data.data.shape, (2, 2))

    def test_render_preview_u8_rejects_unsafe_full_size_output(self) -> None:
        # broadcast_to creates a large logical image without allocating it.
        image = np.broadcast_to(np.array([[1.0]], dtype=np.float32), (100, 100))
        data = FITSData(data=image)

        with self.assertRaisesRegex(ValueError, r"10,000 pixels"):
            render_preview_u8(
                data,
                "Linear",
                "ZScale",
                max_dimension=10,
                max_output_pixels=9_999,
            )

    def test_render_preview_u8_output_limit_can_be_disabled(self) -> None:
        data = FITSData(data=np.arange(16, dtype=np.float32).reshape(4, 4))
        preview_tile = np.array([[10, 20], [30, 40]], dtype=np.uint8)

        with patch("core.fits_service.render_image_u8", return_value=preview_tile):
            preview = render_preview_u8(
                data,
                "Linear",
                "ZScale",
                max_dimension=2,
                max_output_pixels=None,
            )

        self.assertEqual(preview.shape, data.data.shape)

    def test_render_all_non_finite_pixels_returns_black_image(self) -> None:
        service = FITSService()
        service.current_data = FITSData(
            data=np.array([[np.nan, np.inf], [-np.inf, np.nan]], dtype=np.float32)
        )

        result = service.render()

        self.assertEqual(result.image_u8.shape, (2, 2))
        self.assertTrue(np.array_equal(result.image_u8, np.zeros((2, 2), dtype=np.uint8)))

    def test_subsample_strides_large_arrays(self) -> None:
        data = np.arange(2_000 * 1_500, dtype=np.float32).reshape(2_000, 1_500)

        sample = _subsample(data, max_size=1_000)

        self.assertEqual(sample.shape, (1_000, 1_500))
        self.assertTrue(np.array_equal(sample, data[::2, ::1]))

    def test_original_interval_uses_true_full_image_limits(self) -> None:
        interval = _OriginalInterval()
        data = np.array([[100.0, 5.0], [10.0, -3.0]], dtype=np.float32)

        vmin, vmax = interval.get_limits(data)

        self.assertEqual((vmin, vmax), (-3.0, 100.0))

    def test_histogram_returns_counts_and_data_range(self) -> None:
        service = FITSService()
        service.current_data = FITSData(
            data=np.array([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32)
        )

        counts, min_value, max_value = service.histogram(bins=4)

        self.assertEqual(counts.sum(), 3)
        self.assertEqual(min_value, 1.0)
        self.assertEqual(max_value, 3.0)

    def test_finite_data_range_ignores_nan_values(self) -> None:
        service = FITSService()
        service.current_data = FITSData(
            data=np.array([[np.nan, 5.0], [10.0, np.nan]], dtype=np.float32)
        )

        self.assertEqual(service.finite_data_range(), (5.0, 10.0))


if __name__ == "__main__":
    unittest.main()
