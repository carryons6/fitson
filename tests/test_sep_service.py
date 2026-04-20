from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from core.contracts import ROISelection
from core.sep_service import SEPParameters, SEPService
from core.source_catalog import SourceCatalog


class _FakeBackground:
    def __init__(self, level: float, globalrms: float) -> None:
        self.level = level
        self.globalrms = globalrms

    def __array__(self, dtype=None):
        return np.array(self.level, dtype=dtype or np.float32)


class TestSEPService(unittest.TestCase):
    def test_validate_params_rejects_non_positive_threshold(self) -> None:
        service = SEPService()

        with self.assertRaisesRegex(ValueError, "thresh"):
            service.validate_params(SEPParameters(thresh=0))

    def test_validate_params_rejects_small_minarea(self) -> None:
        service = SEPService()

        with self.assertRaisesRegex(ValueError, "minarea"):
            service.validate_params(SEPParameters(minarea=0))

    def test_params_to_payload_returns_plain_mapping(self) -> None:
        service = SEPService()
        params = SEPParameters(
            thresh=4.5,
            minarea=7,
            deblend_nthresh=16,
            deblend_cont=0.01,
            clean=False,
            clean_param=0.8,
        )

        payload = service.params_to_payload(params)

        self.assertEqual(
            payload,
            {
                "thresh": 4.5,
                "minarea": 7,
                "deblend_nthresh": 16,
                "deblend_cont": 0.01,
                "clean": False,
                "clean_param": 0.8,
            },
        )

    def test_extract_runs_sep_and_builds_catalog(self) -> None:
        service = SEPService()
        params = SEPParameters(
            thresh=2.5,
            minarea=9,
            deblend_nthresh=8,
            deblend_cont=0.02,
            bkg_box_size=48,
            bkg_filter_size=5,
        )
        data = np.array([[1, 2], [3, 4]], dtype=np.float32, order="F")
        fake_background = _FakeBackground(level=1.5, globalrms=0.25)
        sep_objects = {"x": np.array([1.0]), "y": np.array([2.0])}
        segmentation_map = np.array([[0, 1], [1, 0]], dtype=np.int32)
        catalog = SourceCatalog()
        wcs = object()

        with patch("core.sep_service.sep.Background", return_value=fake_background) as background_mock:
            with patch("core.sep_service.sep.extract", return_value=(sep_objects, segmentation_map)) as extract_mock:
                with patch(
                    "core.sep_service.SourceCatalog.from_sep_objects",
                    return_value=catalog,
                ) as catalog_mock:
                    result = service.extract(data, params=params, x_offset=10, y_offset=20, wcs=wcs)

        self.assertIs(result, catalog)
        background_mock.assert_called_once()
        bkg_args, bkg_kwargs = background_mock.call_args
        self.assertEqual(bkg_kwargs, {"bw": 48, "bh": 48, "fw": 5, "fh": 5})
        extract_args, extract_kwargs = extract_mock.call_args
        processed = extract_args[0]
        self.assertEqual(processed.dtype, np.float32)
        self.assertTrue(processed.flags["C_CONTIGUOUS"])
        self.assertTrue(np.allclose(processed, np.array([[-0.5, 0.5], [1.5, 2.5]])))
        self.assertEqual(extract_kwargs["thresh"], 2.5)
        self.assertEqual(extract_kwargs["err"], 0.25)
        self.assertEqual(extract_kwargs["minarea"], 9)
        self.assertEqual(extract_kwargs["deblend_nthresh"], 8)
        self.assertEqual(extract_kwargs["deblend_cont"], 0.02)
        self.assertTrue(extract_kwargs["clean"])
        self.assertEqual(extract_kwargs["clean_param"], 1.0)
        self.assertTrue(extract_kwargs["segmentation_map"])
        catalog_mock.assert_called_once_with(
            sep_objects,
            x_offset=10,
            y_offset=20,
            wcs=wcs,
            background_rms=0.25,
            segmentation_map=segmentation_map,
        )

    def test_extract_from_roi_forwards_offsets(self) -> None:
        service = SEPService()
        roi = ROISelection(x0=3, y0=4, width=20, height=10)
        data = np.ones((2, 2), dtype=np.float32)
        params = SEPParameters(thresh=5.0)
        wcs = object()

        with patch.object(service, "extract", return_value=SourceCatalog()) as extract_mock:
            service.extract_from_roi(data, roi, params=params, wcs=wcs)

        extract_mock.assert_called_once_with(
            data,
            params=params,
            x_offset=3,
            y_offset=4,
            wcs=wcs,
        )


if __name__ == "__main__":
    unittest.main()
