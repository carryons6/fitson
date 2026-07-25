from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from astropy.wcs import WCS
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from astroview.app.canvas import ImageCanvas
from astroview.app.main_window import MainWindow
from astroview.core.catalog_service import CatalogSource
from astroview.core.fits_data import FITSData
from astroview.core.wcs_grid import build_wcs_grid


def _simple_wcs() -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [50.5, 40.5]
    wcs.wcs.cdelt = [-0.01, 0.01]
    wcs.wcs.crval = [180.0, 30.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


class TestWCSCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_canvas_draws_and_clears_grid_and_catalog_markers(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.set_image(QImage(100, 80, QImage.Format.Format_Grayscale8))
            canvas.set_wcs_grid(build_wcs_grid(_simple_wcs(), 100, 80))
            self.assertGreater(len(canvas._wcs_grid_items), 0)

            sources = [CatalogSource("42", 180.0, 30.0, 12.0)]
            canvas.set_catalog_sources(sources, [(49.5, 39.5)])
            self.assertEqual(len(canvas._catalog_items), 1)
            canvas.highlight_catalog_source(0)
            self.assertEqual(canvas._catalog_items[0].pen().width(), 2)

            canvas.clear_wcs_grid()
            canvas.clear_catalog_sources()
            self.assertEqual(canvas._wcs_grid_items, [])
            self.assertEqual(canvas._catalog_items, [])
        finally:
            canvas.deleteLater()

    def test_main_window_syncs_wcs_dock_and_grid(self) -> None:
        window = MainWindow()
        try:
            window.initialize(apply_startup_request=False)
            data = FITSData(
                path="wcs.fits",
                data=np.zeros((80, 100), dtype=np.float32),
                wcs=_simple_wcs(),
                has_wcs=True,
            )
            window._frames = [data]
            window._frame_images = [QImage(100, 80, QImage.Format.Format_Grayscale8)]
            window._frame_dirty = [False]
            window._frame_bkg_cache = [None]
            window._frame_residual_cache = [None]
            window._frame_cached_preview_dim = [0]
            window.fits_service.current_data = data

            window._sync_wcs_catalog_state()
            self.assertIsNotNone(window._current_wcs_center)
            self.assertIsNone(window._current_wcs_grid)
            self.assertTrue(window.catalog_overlay_dock.query_button.isEnabled())
            window.catalog_overlay_dock.grid_checkbox.setChecked(True)
            self.assertIsNotNone(window._current_wcs_grid)
            self.assertGreater(len(window.canvas._wcs_grid_items), 0)
        finally:
            window.close()
            window.deleteLater()

    def test_gaia_result_is_projected_and_filtered_to_image(self) -> None:
        window = MainWindow()
        try:
            window.initialize(apply_startup_request=False)
            data = FITSData(
                data=np.zeros((80, 100), dtype=np.float32),
                wcs=_simple_wcs(),
                has_wcs=True,
            )
            window.fits_service.current_data = data
            window._frames = [data]
            window._current_frame_index = 0
            worker = Mock()
            window._active_gaia_query_request_id = 7
            window._gaia_results_enabled = True
            window._gaia_query_worker = worker

            window._handle_gaia_result_for_request(
                7,
                0,
                worker,
                [
                    CatalogSource("inside", 180.0, 30.0, 10.0),
                    CatalogSource("outside", 10.0, -60.0, 12.0),
                ],
            )

            self.assertEqual([source.source_id for source in window._gaia_sources], ["inside"])
            self.assertEqual(window.catalog_overlay_dock.table.rowCount(), 1)
            self.assertEqual(len(window.canvas._catalog_items), 1)
        finally:
            window._gaia_query_worker = None
            window._active_gaia_query_request_id = None
            window._gaia_results_enabled = False
            window.close()
            window.deleteLater()

    def test_cancel_invalidates_already_queued_gaia_result(self) -> None:
        window = MainWindow()
        worker = Mock()
        thread = Mock()
        thread.isRunning.return_value = True
        window._gaia_query_worker = worker
        window._gaia_query_thread = thread
        window._active_gaia_query_request_id = 8
        window._gaia_results_enabled = True
        window._current_frame_index = 0
        try:
            self.assertFalse(window._stop_gaia_query(wait=False))
            self.assertFalse(window._gaia_results_enabled)
            window._handle_gaia_result_for_request(
                8,
                0,
                worker,
                [CatalogSource("stale", 180.0, 30.0, 10.0)],
            )
            self.assertEqual(window._gaia_sources, [])
            worker.cancel.assert_called_once_with()
            thread.requestInterruption.assert_called_once_with()
        finally:
            window._gaia_query_worker = None
            window._gaia_query_thread = None
            window._active_gaia_query_request_id = None
            window.close()
            window.deleteLater()

    def test_grid_build_is_lazy_and_cached_for_same_wcs(self) -> None:
        window = MainWindow()
        try:
            window.initialize(apply_startup_request=False)
            wcs = _simple_wcs()
            data = FITSData(data=np.zeros((80, 100)), wcs=wcs, has_wcs=True)
            window._frames = [data]
            window.fits_service.current_data = data
            with patch("astroview.app.main_window.build_wcs_grid", wraps=build_wcs_grid) as builder:
                window._sync_wcs_catalog_state()
                builder.assert_not_called()
                window.catalog_overlay_dock.grid_checkbox.setChecked(True)
                self.assertEqual(builder.call_count, 1)
                window._sync_wcs_catalog_state()
                self.assertEqual(builder.call_count, 1)
        finally:
            window.close()
            window.deleteLater()

    def test_comparison_mode_blocks_gaia_query_start(self) -> None:
        window = MainWindow()
        try:
            window.initialize(apply_startup_request=False)
            data = FITSData(data=np.zeros((80, 100)), wcs=_simple_wcs(), has_wcs=True)
            window._frames = [data]
            window.fits_service.current_data = data
            window._sync_wcs_catalog_state()
            window._comparison_active = True
            window._start_gaia_query(1.0, 10, 18.0)
            self.assertIsNone(window._gaia_query_thread)
        finally:
            window._comparison_active = False
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
