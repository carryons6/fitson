from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from astropy.wcs import WCS
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from astroview.app.ds9_overlay import MAX_RENDERED_REGIONS, build_ds9_overlays
from astroview.app.main_window import MainWindow
from astroview.core.contracts import ROISelection
from astroview.core.ds9_regions import DS9Attribute, DS9Region, DS9RegionDocument
from astroview.core.fits_data import FITSData


def _simple_wcs() -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [50.5, 40.5]
    wcs.wcs.cdelt = [-0.01, 0.01]
    wcs.wcs.crval = [180.0, 30.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


class TestDS9OverlayBuilder(unittest.TestCase):
    def test_image_coordinates_are_converted_from_one_based_and_clipped(self) -> None:
        document = DS9RegionDocument(
            regions=(
                DS9Region("image", "point", (1.0, 1.0)),
                DS9Region("image", "circle", (1.0, 1.0, 20.0)),
                DS9Region("image", "point", (1.0e6, 1.0e6)),
            )
        )
        result = build_ds9_overlays(document, width=100, height=80)

        self.assertEqual(result.overlays[0]["points"], [(0.0, 0.0)])
        self.assertGreaterEqual(result.skipped_regions, 1)
        for overlay in result.overlays:
            for x, y in overlay["points"]:
                self.assertLessEqual(abs(x), 200.0)
                self.assertLessEqual(abs(y), 200.0)

    def test_sky_regions_require_wcs_and_project_to_pixels(self) -> None:
        document = DS9RegionDocument(
            regions=(
                DS9Region("icrs", "point", (180.0, 30.0)),
                DS9Region("fk5", "circle", (180.0, 30.0, 0.05)),
            )
        )
        without_wcs = build_ds9_overlays(document, width=100, height=80)
        with_wcs = build_ds9_overlays(document, width=100, height=80, wcs=_simple_wcs())

        self.assertEqual(without_wcs.skipped_without_wcs, 2)
        self.assertEqual(len(with_wcs.overlays), 2)
        x, y = with_wcs.overlays[0]["points"][0]
        self.assertAlmostEqual(x, 49.5, places=2)
        self.assertAlmostEqual(y, 39.5, places=2)

    def test_renderer_has_a_stricter_region_budget_than_parser(self) -> None:
        region = DS9Region("image", "point", (1.0, 1.0))
        document = DS9RegionDocument(regions=(region,) * (MAX_RENDERED_REGIONS + 10))
        result = build_ds9_overlays(document, width=10, height=10)
        self.assertEqual(len(result.overlays), MAX_RENDERED_REGIONS)
        self.assertEqual(result.skipped_regions, 10)


class TestDS9MainWindowIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _window(self) -> MainWindow:
        window = MainWindow()
        window.initialize(apply_startup_request=False)
        frame = FITSData(
            path="regions.fits",
            data=np.zeros((80, 100), dtype=float),
            wcs=_simple_wcs(),
            has_wcs=True,
        )
        window._frames = [frame]
        window._frame_images = [QImage(100, 80, QImage.Format.Format_Grayscale8)]
        window._frame_dirty = [False]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._frame_cached_preview_dim = [0]
        window.fits_service.current_data = frame
        return window

    def test_document_changes_draw_regions_and_selection_focuses(self) -> None:
        window = self._window()
        document = DS9RegionDocument(
            regions=(
                DS9Region(
                    "image",
                    "circle",
                    (50.0, 40.0, 5.0),
                    attributes=(DS9Attribute("text", "target"),),
                ),
            )
        )
        try:
            window.ds9_region_dock.set_document(document)
            self.assertEqual(len(window.canvas._region_path_items), 1)
            self.assertEqual(len(window.canvas._region_label_items), 1)
            window._focus_ds9_region(0)
            self.assertEqual(window.canvas._region_path_items[0].pen().width(), 3)
        finally:
            window.close()
            window.deleteLater()

    def test_current_roi_and_aperture_can_be_captured_and_exported(self) -> None:
        window = self._window()
        try:
            window._last_measurement_roi = ROISelection(10, 20, 8, 6)
            window._capture_roi_as_region()
            first = window.ds9_region_dock.document().regions[0]
            self.assertEqual(first.shape, "box")
            self.assertEqual(first.parameters[:2], (15.0, 24.0))

            window._measure_aperture(20.0, 20.0, 4.0, 7.0, 10.0)
            window._capture_aperture_as_region()
            second = window.ds9_region_dock.document().regions[1]
            self.assertEqual(second.shape, "circle")
            self.assertEqual(second.parameters, (21.0, 21.0, 4.0))
        finally:
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
