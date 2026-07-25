import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from astropy.io import fits

from core.fits_data import (
    DEFAULT_MAX_DECODED_BYTES,
    DEFAULT_MAX_FRAMES,
    DEFAULT_MAX_PIXELS,
    FITSData,
    HDUInfo,
    _enforce_load_limits,
    _read_hdu_data,
    _scan_image_hdus,
    _validate_input_container,
    open_fits_container,
)


class _FakeImageHDU:
    def __init__(self, *, header, shape, data=None, error=None, name='PRIMARY'):
        self.header = header
        self.shape = shape
        self._data = data
        self._error = error
        self.name = name

    @property
    def data(self):
        if self._error is not None:
            raise self._error
        return self._data


class _FakeHDUList(list):
    def close(self):
        return None


class _FakeContextHDUList(_FakeHDUList):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestFITSData(unittest.TestCase):
    def test_scan_image_hdus_uses_header_metadata_without_touching_data(self):
        hdu = _FakeImageHDU(
            header={"BITPIX": 16, "BZERO": 32768, "BSCALE": 1},
            shape=(8120, 8120),
            error=AssertionError("_scan_image_hdus should not access hdu.data"),
        )

        with patch("core.fits_data._is_image_hdu", return_value=True):
            result = _scan_image_hdus([hdu])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].dimensions, (8120, 8120))
        self.assertEqual(result[0].dtype_name, "uint16")

    def test_load_retries_without_memmap_for_scaled_integer_data(self):
        first_header = {"BITPIX": 16, "BZERO": 32768, "BSCALE": 1, "OBJECT": "FIRST"}
        fallback_header = {
            "BITPIX": 16,
            "BZERO": 32768,
            "BSCALE": 1,
            "OBJECT": "FALLBACK",
        }
        memmap_error = ValueError(
            "Cannot load a memory-mapped image: BZERO/BSCALE/BLANK header keywords present"
        )
        first_hdul = _FakeHDUList([
            _FakeImageHDU(header=first_header, shape=(2, 3), error=memmap_error),
        ])
        fallback_hdul = _FakeContextHDUList([
            _FakeImageHDU(
                header=fallback_header,
                shape=(3, 2),
                data=np.array([[1, 2], [3, 4], [5, 6]], dtype=">u2"),
                name="FALLBACK",
            ),
        ])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "scaled.fits"
            path.write_bytes(b"SIMPLE  ")
            with patch("core.fits_data.fits.open", side_effect=[first_hdul, fallback_hdul]) as open_mock:
                with patch("core.fits_data._is_image_hdu", return_value=True):
                    with patch(
                        "core.fits_data._build_frame_wcs",
                        side_effect=lambda header: (header["OBJECT"], True),
                    ):
                        data = FITSData.load(str(path))

        self.assertEqual(data.hdu_index, 0)
        self.assertEqual(data.header["OBJECT"], "FALLBACK")
        self.assertEqual(data.wcs, "FALLBACK")
        self.assertTrue(data.has_wcs)
        self.assertEqual(data.available_hdus[0].name, "FALLBACK")
        self.assertEqual(data.available_hdus[0].dimensions, (3, 2))
        self.assertEqual(data.available_hdus[0].dtype_name, "uint16")
        self.assertIsNotNone(data.data)
        self.assertEqual(data.data.shape, (3, 2))
        self.assertTrue(data.data.dtype.isnative)
        self.assertEqual(data.data.dtype.kind, "u")
        self.assertEqual(open_mock.call_args_list[0].kwargs, {"memmap": True})
        self.assertEqual(open_mock.call_args_list[1].kwargs, {"memmap": False})

    def test_load_frames_splits_multidimensional_cube_into_2d_frames(self):
        cube = np.arange(3 * 2 * 4, dtype=np.float32).reshape(3, 2, 4)
        hdul = _FakeHDUList([
            _FakeImageHDU(header={"BITPIX": -32}, shape=cube.shape, data=cube),
        ])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "cube.fits"
            path.write_bytes(b"SIMPLE  ")
            with patch("core.fits_data.fits.open", return_value=hdul):
                with patch(
                    "core.fits_data._scan_image_hdus",
                    return_value=[HDUInfo(index=0, name="PRIMARY", dimensions=cube.shape, dtype_name="float32")],
                ):
                    with patch("core.fits_data._is_image_hdu", return_value=True):
                        with patch("core.fits_data.WCS", side_effect=Exception("no wcs")):
                            frames = FITSData.load_frames(str(path), source_group_id=7)

        self.assertEqual(len(frames), 3)
        self.assertTrue(all(frame.data is not None for frame in frames))
        self.assertEqual([frame.data.shape for frame in frames], [(2, 4), (2, 4), (2, 4)])
        self.assertTrue(np.array_equal(frames[0].data, cube[0]))
        self.assertTrue(np.array_equal(frames[1].data, cube[1]))
        self.assertTrue(np.array_equal(frames[2].data, cube[2]))
        self.assertEqual([frame.frame_index for frame in frames], [0, 1, 2])
        self.assertEqual([frame.frame_count for frame in frames], [3, 3, 3])
        self.assertEqual([frame.source_group_id for frame in frames], [7, 7, 7])

    def test_load_returns_first_frame_for_multidimensional_cube(self):
        cube = np.arange(3 * 2 * 2, dtype=np.float32).reshape(3, 2, 2)
        hdul = _FakeHDUList([
            _FakeImageHDU(header={"BITPIX": -32}, shape=cube.shape, data=cube),
        ])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "cube.fits"
            path.write_bytes(b"SIMPLE  ")
            with patch("core.fits_data.fits.open", return_value=hdul):
                with patch(
                    "core.fits_data._scan_image_hdus",
                    return_value=[HDUInfo(index=0, name="PRIMARY", dimensions=cube.shape, dtype_name="float32")],
                ):
                    with patch("core.fits_data._is_image_hdu", return_value=True):
                        with patch("core.fits_data.WCS", side_effect=Exception("no wcs")):
                            data = FITSData.load(str(path))

        self.assertEqual(data.frame_index, 0)
        self.assertEqual(data.frame_count, 3)
        self.assertEqual(data.data.shape, (2, 2))
        self.assertTrue(np.array_equal(data.data, cube[0]))

    def test_loads_real_astropy_image_from_temporary_fits(self):
        image = np.arange(20, dtype=np.float32).reshape(4, 5)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "image.fits"
            fits.PrimaryHDU(data=image).writeto(path)

            loaded = FITSData.load(str(path))

        self.assertEqual(loaded.hdu_index, 0)
        self.assertEqual(loaded.data.shape, (4, 5))
        self.assertTrue(np.array_equal(loaded.data, image))

    def test_uint8_load_detaches_memmap_and_releases_source_file(self):
        image = np.arange(20, dtype=np.uint8).reshape(4, 5)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "uint8.fits"
            fits.PrimaryHDU(data=image).writeto(path)

            loaded = FITSData.load(str(path))
            self.assertTrue(loaded.data.flags.owndata)
            path.unlink()

        self.assertTrue(np.array_equal(loaded.data, image))

    def test_native_heap_array_is_reused_without_a_second_full_copy(self):
        image = np.arange(20, dtype=np.float64).reshape(4, 5).copy()
        hdul = _FakeHDUList([
            _FakeImageHDU(header={"BITPIX": -64}, shape=image.shape, data=image),
        ])

        loaded = _read_hdu_data("heap-backed.fits", 0, hdul)

        self.assertIs(loaded, image)

    def test_explicit_table_hdu_is_rejected_with_readable_error(self):
        column = fits.Column(name="flux", format="E", array=np.array([1.0, 2.0], dtype=np.float32))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "table.fits"
            fits.HDUList([
                fits.PrimaryHDU(data=np.zeros((2, 2), dtype=np.float32)),
                fits.BinTableHDU.from_columns([column]),
            ]).writeto(path)

            with self.assertRaisesRegex(ValueError, r"HDU 1 .*not an image HDU"):
                FITSData.load(str(path), hdu_index=1)

    def test_explicit_empty_and_one_dimensional_hdus_are_rejected(self):
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            empty_path = directory_path / "empty.fits"
            one_d_path = directory_path / "one-d.fits"
            fits.PrimaryHDU().writeto(empty_path)
            fits.PrimaryHDU(data=np.arange(8, dtype=np.int16)).writeto(one_d_path)

            with self.assertRaisesRegex(ValueError, r"HDU 0 is empty"):
                FITSData.load(str(empty_path), hdu_index=0)
            with self.assertRaisesRegex(ValueError, r"HDU 0 is one-dimensional"):
                FITSData.load(str(one_d_path), hdu_index=0)

    def test_cube_frame_limit_is_checked_and_can_be_raised_or_disabled(self):
        cube = np.arange(5 * 2 * 3, dtype=np.float32).reshape(5, 2, 3)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cube.fits"
            fits.PrimaryHDU(data=cube).writeto(path)

            with self.assertRaisesRegex(ValueError, r"expand into 5 frames"):
                FITSData.load_frames(str(path), max_frames=4)
            raised_frames = FITSData.load_frames(str(path), max_frames=5)
            unlimited_frames = FITSData.load_frames(str(path), max_frames=None)

        self.assertEqual(len(raised_frames), 5)
        self.assertEqual(len(unlimited_frames), 5)

    def test_compressed_image_is_budgeted_from_metadata_before_decode(self):
        image = np.arange(42, dtype=np.int16).reshape(6, 7)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "compressed.fits"
            fits.HDUList([
                fits.PrimaryHDU(),
                fits.CompImageHDU(data=image),
            ]).writeto(path)

            with self.assertRaisesRegex(ValueError, r"42 pixels"):
                FITSData.load(str(path), hdu_index=1, max_pixels=41)
            loaded = FITSData.load(str(path), hdu_index=1, max_pixels=42)

        self.assertTrue(np.array_equal(loaded.data, image))

    def test_outer_compression_is_rejected_before_astropy_open(self):
        signatures = {
            "gzip": b"\x1f\x8b\x08\x00",
            "lzw": b"\x1f\x9d\x90\x00",
            "bzip2": b"BZh91AY&SY",
            "zip": b"PK\x03\x04\x14\x00",
            "xz": b"\xfd7zXZ\x00\x00\x04",
            "lzma": b"]\x00\x00\x80\x00\xff",
        }
        with TemporaryDirectory() as directory:
            for label, payload in signatures.items():
                with self.subTest(label=label):
                    path = Path(directory) / f"disguised-{label}.fits"
                    path.write_bytes(payload)
                    with patch("core.fits_data._astropy_fits") as astropy_mock:
                        with self.assertRaisesRegex(ValueError, r"compression is not supported safely"):
                            FITSData.load(str(path), max_pixels=1)
                    astropy_mock.assert_not_called()

    def test_missing_and_non_regular_inputs_are_not_delegated_to_astropy(self):
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            missing_path = directory_path / "missing.fits"
            with patch("core.fits_data._astropy_fits") as astropy_mock:
                with self.assertRaises(FileNotFoundError):
                    with open_fits_container(str(missing_path)):
                        self.fail("A missing FITS path must not be opened")
            astropy_mock.assert_not_called()

            with patch("core.fits_data._astropy_fits") as astropy_mock:
                with self.assertRaisesRegex(ValueError, r"regular local file"):
                    with open_fits_container(str(directory_path)):
                        self.fail("A directory must not be opened as FITS")
            astropy_mock.assert_not_called()

    def test_open_uses_the_validated_handle_if_path_resolution_changes(self):
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            verified_path = directory_path / "verified.fits"
            replacement_path = directory_path / "replacement.fits"
            fits.PrimaryHDU(data=np.ones((2, 2), dtype=np.float32)).writeto(verified_path)
            replacement_path.write_bytes(b"\x1f\x8b\x08\x00replacement gzip stream")

            real_path_open = Path.open
            real_validate = _validate_input_container
            path_generation = "verified"
            path_open_generations: list[str] = []
            astropy_sources: list[object] = []

            def resolve_current_path(_source, mode="r", *args, **kwargs):
                path_open_generations.append(path_generation)
                resolved = verified_path if path_generation == "verified" else replacement_path
                return real_path_open(resolved, mode, *args, **kwargs)

            def validate_then_replace(stream, path):
                nonlocal path_generation
                real_validate(stream, path)
                path_generation = "replacement"

            def observed_astropy_open(source, **kwargs):
                astropy_sources.append(source)
                self.assertEqual(path_generation, "replacement")
                self.assertNotIsInstance(source, (str, Path))
                self.assertEqual(source.tell(), 0)
                self.assertEqual(source.read(8), b"SIMPLE  ")
                source.seek(0)
                return fits.open(source, **kwargs)

            astropy_api = Mock()
            astropy_api.open.side_effect = observed_astropy_open
            with patch.object(Path, "open", autospec=True, side_effect=resolve_current_path):
                with patch(
                    "core.fits_data._validate_input_container",
                    side_effect=validate_then_replace,
                ):
                    with patch("core.fits_data._astropy_fits", return_value=astropy_api):
                        with open_fits_container("logical.fits") as hdul:
                            self.assertEqual(len(hdul), 1)
                            self.assertFalse(astropy_sources[0].closed)

            self.assertEqual(path_open_generations, ["verified"])
            self.assertTrue(astropy_sources[0].closed)

    def test_memmap_fallback_keeps_the_original_source_when_path_resolution_changes(self):
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            verified_path = directory_path / "verified-scaled.fits"
            replacement_path = directory_path / "replacement.fits"
            original = np.array([[1, 2], [3, 4]], dtype=np.uint16)
            fits.PrimaryHDU(data=original).writeto(verified_path)
            fits.PrimaryHDU(data=np.arange(9, dtype=np.float32).reshape(3, 3)).writeto(
                replacement_path
            )

            real_path_open = Path.open
            real_validate = _validate_input_container
            path_generation = "verified"
            path_open_generations: list[str] = []

            def resolve_current_path(_source, mode="r", *args, **kwargs):
                path_open_generations.append(path_generation)
                resolved = verified_path if path_generation == "verified" else replacement_path
                return real_path_open(resolved, mode, *args, **kwargs)

            def validate_then_replace(stream, path):
                nonlocal path_generation
                real_validate(stream, path)
                path_generation = "replacement"

            with patch.object(Path, "open", autospec=True, side_effect=resolve_current_path):
                with patch(
                    "core.fits_data._validate_input_container",
                    side_effect=validate_then_replace,
                ):
                    loaded = FITSData.load("logical.fits", max_pixels=4)

            self.assertEqual(path_open_generations, ["verified"])
            self.assertTrue(np.array_equal(loaded.data, original))
            self.assertEqual(loaded.data.shape, (2, 2))
            self.assertEqual(loaded.header["NAXIS1"], 2)
            self.assertEqual(loaded.header["NAXIS2"], 2)
            self.assertEqual(loaded.available_hdus[0].dimensions, (2, 2))
            verified_path.unlink()
            self.assertFalse(verified_path.exists())

    def test_memmap_fallback_rechecks_replacement_hdu_budget_before_data_access(self):
        first_hdul = _FakeHDUList([
            _FakeImageHDU(
                header={"BITPIX": 16, "BZERO": 32768, "BSCALE": 1},
                shape=(2, 2),
                error=ValueError("Cannot load a memory-mapped scaled image"),
            ),
        ])
        fallback_hdul = _FakeHDUList([
            _FakeImageHDU(
                header={"BITPIX": -32},
                shape=(3, 3),
                error=AssertionError("fallback data was read before budget validation"),
            ),
        ])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "stable.fits"
            path.write_bytes(b"SIMPLE  ")
            with patch(
                "core.fits_data.fits.open",
                side_effect=[first_hdul, fallback_hdul],
            ) as open_mock:
                with patch("core.fits_data._is_image_hdu", return_value=True):
                    with self.assertRaisesRegex(ValueError, r"9 pixels"):
                        FITSData.load(str(path), max_pixels=4)

        self.assertEqual(open_mock.call_count, 2)
        self.assertEqual(open_mock.call_args_list[0].kwargs, {"memmap": True})
        self.assertEqual(open_mock.call_args_list[1].kwargs, {"memmap": False})

    def test_pixel_budget_is_enforced_before_hdu_data_access(self):
        hdu = _FakeImageHDU(
            header={"BITPIX": -32},
            shape=(50_000, 50_000),
            error=AssertionError("unsafe hdu.data access"),
        )
        hdul = _FakeHDUList([hdu])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.fits"
            path.write_bytes(b"SIMPLE  ")
            with patch("core.fits_data.fits.open", return_value=hdul):
                with patch("core.fits_data._is_image_hdu", return_value=True):
                    with self.assertRaisesRegex(ValueError, r"2,500,000,000 pixels"):
                        FITSData.load(str(path), hdu_index=0, max_pixels=1_000)

    def test_default_budgets_admit_an_8k_float64_image(self):
        _enforce_load_limits(
            (8_192, 8_192),
            {"BITPIX": -64},
            hdu_index=0,
            max_pixels=DEFAULT_MAX_PIXELS,
            max_decoded_bytes=DEFAULT_MAX_DECODED_BYTES,
            max_frames=DEFAULT_MAX_FRAMES,
        )

    def test_default_budgets_stop_immediately_beyond_8k_float64(self):
        with self.assertRaisesRegex(ValueError, r"67,117,056 pixels"):
            _enforce_load_limits(
                (8_192, 8_193),
                {"BITPIX": 8},
                hdu_index=0,
                max_pixels=DEFAULT_MAX_PIXELS,
                max_decoded_bytes=DEFAULT_MAX_DECODED_BYTES,
                max_frames=DEFAULT_MAX_FRAMES,
            )
        with self.assertRaisesRegex(ValueError, r"536,936,448 decoded bytes"):
            _enforce_load_limits(
                (8_192, 8_193),
                {"BITPIX": -64},
                hdu_index=0,
                max_pixels=None,
                max_decoded_bytes=DEFAULT_MAX_DECODED_BYTES,
                max_frames=DEFAULT_MAX_FRAMES,
            )

    def test_decoded_byte_budget_uses_header_bitpix(self):
        with self.assertRaisesRegex(ValueError, r"800 decoded bytes"):
            _enforce_load_limits(
                (10, 10),
                {"BITPIX": -64},
                hdu_index=0,
                max_pixels=None,
                max_decoded_bytes=799,
                max_frames=None,
            )


if __name__ == "__main__":
    unittest.main()
