import unittest
from unittest.mock import patch

import numpy as np

from core.fits_data import FITSData, HDUInfo, _scan_image_hdus


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
        header = {"BITPIX": 16, "BZERO": 32768, "BSCALE": 1}
        memmap_error = ValueError(
            "Cannot load a memory-mapped image: BZERO/BSCALE/BLANK header keywords present"
        )
        first_hdul = _FakeHDUList([
            _FakeImageHDU(header=header, shape=(2, 3), error=memmap_error),
        ])
        fallback_hdul = _FakeContextHDUList([
            _FakeImageHDU(
                header=header,
                shape=(2, 3),
                data=np.array([[1, 2, 3], [4, 5, 6]], dtype=">u2"),
            ),
        ])

        with patch("core.fits_data.fits.open", side_effect=[first_hdul, fallback_hdul]) as open_mock:
            with patch(
                "core.fits_data._scan_image_hdus",
                return_value=[HDUInfo(index=0, name="PRIMARY", dimensions=(2, 3), dtype_name="uint16")],
            ):
                with patch("core.fits_data.WCS", side_effect=Exception("no wcs")):
                    data = FITSData.load("scaled.fits")

        self.assertEqual(data.hdu_index, 0)
        self.assertEqual(data.available_hdus[0].dtype_name, "uint16")
        self.assertIsNotNone(data.data)
        self.assertEqual(data.data.shape, (2, 3))
        self.assertTrue(data.data.dtype.isnative)
        self.assertEqual(data.data.dtype.kind, "u")
        self.assertEqual(open_mock.call_args_list[0].kwargs, {"memmap": True})
        self.assertEqual(open_mock.call_args_list[1].kwargs, {"memmap": False})


if __name__ == "__main__":
    unittest.main()
